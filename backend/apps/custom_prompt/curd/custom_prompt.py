# ========= 【改造标记 CUSTOM-PROMPT】↓ 开源自定义提示词 CURD + 问数召回（BM25），替换 sqlbot_xpack 闭源实现（新建文件） =========
import datetime
from xml.dom.minidom import parseString

from sqlalchemy import BigInteger, and_, delete, func, or_, select, text, update

from apps.custom_prompt.models.custom_prompt_model import (
    CustomPrompt,
    CustomPromptInfo,
    CustomPromptInfoResult,
    CustomPromptTypeEnum,
)
from apps.datasource.models.datasource import CoreDatasource
from apps.system.models.system_model import AssistantModel
from common.core.config import settings
from common.core.deps import SessionDep, Trans
from common.utils.dict_to_xml import dict_to_xml

# ========= 【改造标记 CUSTOM-PROMPT】↓ BM25 关键词检索工具，替换"全量注入"为按问题召回 =========
from common.utils.keyword_retrieval import bm25_retrieve
# ========= 【改造标记 CUSTOM-PROMPT】↑ 导入结束 =========


def get_custom_prompt_base_query(oid: int, custom_prompt_type: CustomPromptTypeEnum,
                                 name: str | None = None):
    stmt = select(CustomPrompt.id).where(
        CustomPrompt.oid == oid,
        CustomPrompt.type == custom_prompt_type,
    )
    if name and name.strip() != '':
        stmt = stmt.where(CustomPrompt.name.ilike(f'%{name.strip()}%'))
    return stmt.order_by(CustomPrompt.create_time.desc())


def build_custom_prompt_query(session: SessionDep, oid: int, custom_prompt_type: CustomPromptTypeEnum,
                              name: str | None = None, paginate: bool = True, current_page: int = 1,
                              page_size: int = 10, ds_list: list[int] | None = None,
                              adv_list: list[int] | None = None):
    base = get_custom_prompt_base_query(oid, custom_prompt_type, name)

    if ds_list is not None and len(ds_list) > 0:
        datasource_conditions = [
            CustomPrompt.datasource_ids.contains([ds_id]) for ds_id in ds_list
        ]
        base = base.where(
            or_(
                CustomPrompt.specific_ds.is_(False),
                and_(CustomPrompt.specific_ds.is_(True), *datasource_conditions),
            )
        )

    if adv_list is not None and len(adv_list) > 0:
        base = base.where(CustomPrompt.advanced_application.in_(adv_list))

    count_stmt = select(func.count()).select_from(base.subquery())
    total_count = session.execute(count_stmt).scalar()

    if paginate:
        page_size = max(10, page_size)
        total_pages = (total_count + page_size - 1) // page_size
        current_page = max(1, min(current_page, total_pages)) if total_pages > 0 else 1

        paginated_ids = (
            base
            .offset((current_page - 1) * page_size)
            .limit(page_size)
            .subquery()
        )
    else:
        total_pages = 1
        current_page = 1
        page_size = total_count if total_count and total_count > 0 else 0
        paginated_ids = base.subquery()

    datasource_names_subquery = (
        select(
            func.jsonb_array_elements(CustomPrompt.datasource_ids).cast(BigInteger).label('ds_id'),
            CustomPrompt.id.label('cp_id'),
        )
        .where(CustomPrompt.id.in_(paginated_ids))
        .subquery()
    )

    stmt = (
        select(
            CustomPrompt.id,
            CustomPrompt.oid,
            CustomPrompt.type,
            CustomPrompt.name,
            CustomPrompt.create_time,
            CustomPrompt.prompt,
            CustomPrompt.specific_ds,
            CustomPrompt.datasource_ids,
            func.jsonb_agg(CoreDatasource.name).filter(CoreDatasource.id.isnot(None)).label('datasource_names'),
            CustomPrompt.advanced_application,
            AssistantModel.name.label('advanced_application_name'),
        )
        .outerjoin(
            datasource_names_subquery,
            CustomPrompt.id == datasource_names_subquery.c.cp_id,
        )
        .outerjoin(
            CoreDatasource,
            CoreDatasource.id == datasource_names_subquery.c.ds_id,
        )
        .outerjoin(
            AssistantModel,
            and_(CustomPrompt.advanced_application == AssistantModel.id, AssistantModel.type == 1),
        )
        .where(CustomPrompt.id.in_(paginated_ids))
        .group_by(
            CustomPrompt.id,
            CustomPrompt.oid,
            CustomPrompt.type,
            CustomPrompt.name,
            CustomPrompt.create_time,
            CustomPrompt.prompt,
            CustomPrompt.specific_ds,
            CustomPrompt.datasource_ids,
            CustomPrompt.advanced_application,
            AssistantModel.name,
        )
        .order_by(CustomPrompt.create_time.desc())
    )

    return stmt, total_count, total_pages, current_page, page_size


def execute_custom_prompt_query(session: SessionDep, stmt) -> list[CustomPromptInfoResult]:
    _list = []
    for row in session.execute(stmt):
        _list.append(CustomPromptInfoResult(
            id=row.id,
            oid=row.oid,
            type=row.type,
            create_time=row.create_time,
            name=row.name,
            prompt=row.prompt,
            specific_ds=row.specific_ds if row.specific_ds is not None else False,
            datasource_ids=row.datasource_ids if row.datasource_ids is not None else [],
            datasource_names=row.datasource_names if row.datasource_names is not None else [],
            advanced_application=str(row.advanced_application) if row.advanced_application else None,
            advanced_application_name=row.advanced_application_name,
        ))
    return _list


def page_custom_prompt(session: SessionDep, custom_prompt_type: CustomPromptTypeEnum,
                       current_page: int = 1, page_size: int = 10, name: str | None = None,
                       oid: int | None = 1, ds_list: list[int] | None = None,
                       adv_list: list[int] | None = None):
    stmt, total_count, total_pages, current_page, page_size = build_custom_prompt_query(
        session, oid, custom_prompt_type, name, True, current_page, page_size, ds_list, adv_list
    )
    _list = execute_custom_prompt_query(session, stmt)
    return current_page, page_size, total_count, total_pages, _list


def get_all_custom_prompt(session: SessionDep, custom_prompt_type: CustomPromptTypeEnum,
                          name: str | None = None, oid: int | None = 1,
                          ds_list: list[int] | None = None, adv_list: list[int] | None = None):
    stmt, total_count, total_pages, current_page, page_size = build_custom_prompt_query(
        session, oid, custom_prompt_type, name, False, ds_list=ds_list, adv_list=adv_list
    )
    return execute_custom_prompt_query(session, stmt)


def _validate_custom_prompt(session: SessionDep, info: CustomPromptInfo, oid: int, trans: Trans,
                            exclude_id: int | None = None):
    if not info.name or not info.name.strip():
        raise Exception(trans('i18n_custom_prompt.name_cannot_be_empty'))
    if not info.prompt or not info.prompt.strip():
        raise Exception(trans('i18n_custom_prompt.prompt_cannot_be_empty'))
    if not info.type:
        raise Exception(trans('i18n_custom_prompt.type_cannot_be_empty'))

    specific_ds = info.specific_ds if info.specific_ds is not None else False
    datasource_ids = info.datasource_ids if info.datasource_ids is not None else []
    if specific_ds and not datasource_ids and info.advanced_application is None:
        raise Exception(trans('i18n_data_training.datasource_assistant_cannot_be_none'))

    exists_query = session.query(CustomPrompt).filter(
        CustomPrompt.name == info.name.strip(),
        CustomPrompt.oid == oid,
        CustomPrompt.type == info.type,
    )
    if exclude_id is not None:
        exists_query = exists_query.filter(CustomPrompt.id != exclude_id)

    exists_query = exists_query.filter(
        or_(
            and_(
                CustomPrompt.specific_ds.is_(True),
                CustomPrompt.datasource_ids.isnot(None),
                func.jsonb_array_length(CustomPrompt.datasource_ids) > 0,
            ),
            CustomPrompt.specific_ds.is_(False),
        )
    )

    if session.query(exists_query.exists()).scalar():
        raise Exception(trans('i18n_custom_prompt.exists_in_db'))


def create_custom_prompt(session: SessionDep, info: CustomPromptInfo, oid: int, trans: Trans):
    _validate_custom_prompt(session, info, oid, trans)

    specific_ds = info.specific_ds if info.specific_ds is not None else False
    datasource_ids = info.datasource_ids if info.datasource_ids is not None else []

    row = CustomPrompt(
        oid=oid,
        type=info.type,
        create_time=datetime.datetime.now(),
        name=info.name.strip(),
        prompt=info.prompt.strip(),
        specific_ds=specific_ds,
        datasource_ids=datasource_ids,
        advanced_application=info.advanced_application,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    session.commit()
    return row.id


def update_custom_prompt(session: SessionDep, info: CustomPromptInfo, oid: int, trans: Trans):
    count = session.query(CustomPrompt).filter(
        CustomPrompt.oid == oid,
        CustomPrompt.id == info.id,
    ).count()
    if count == 0:
        raise Exception(trans('i18n_custom_prompt.not_exists'))

    _validate_custom_prompt(session, info, oid, trans, exclude_id=info.id)

    specific_ds = info.specific_ds if info.specific_ds is not None else False
    datasource_ids = info.datasource_ids if info.datasource_ids is not None else []

    stmt = update(CustomPrompt).where(
        and_(CustomPrompt.id == info.id, CustomPrompt.oid == oid)
    ).values(
        name=info.name.strip(),
        prompt=info.prompt.strip(),
        type=info.type,
        specific_ds=specific_ds,
        datasource_ids=datasource_ids,
        advanced_application=info.advanced_application,
    )
    session.execute(stmt)
    session.commit()
    return info.id


def delete_custom_prompt(session: SessionDep, ids: list[int], oid: int):
    stmt = delete(CustomPrompt).where(
        and_(CustomPrompt.oid == oid, CustomPrompt.id.in_(ids))
    )
    session.execute(stmt)
    session.commit()


def batch_create_custom_prompt(session: SessionDep, info_list: list[CustomPromptInfo], oid: int, trans: Trans):
    if not info_list:
        return {
            'success_count': 0,
            'failed_records': [],
            'duplicate_count': 0,
            'original_count': 0,
            'deduplicated_count': 0,
        }

    failed_records = []
    success_count = 0

    unique_records = {}
    duplicate_records = []

    for info in info_list:
        specific_ds = info.specific_ds if info.specific_ds is not None else False
        name_key = info.name.strip().lower() if info.name else ''
        filtered_datasource_names = []
        if specific_ds and info.datasource_names:
            filtered_datasource_names = sorted(
                [d.strip().lower() for d in info.datasource_names if d and d.strip()])
        unique_key = (name_key, ','.join(filtered_datasource_names), str(specific_ds))
        if unique_key in unique_records:
            duplicate_records.append(info)
        else:
            unique_records[unique_key] = info

    deduplicated_list = list(unique_records.values())

    datasource_name_to_id = {}
    datasource_stmt = select(CoreDatasource.id, CoreDatasource.name).where(CoreDatasource.oid == oid)
    for ds in session.execute(datasource_stmt).all():
        datasource_name_to_id[ds.name.strip()] = ds.id

    valid_records = []
    for info in deduplicated_list:
        error_messages = []

        if not info.name or not info.name.strip():
            error_messages.append(trans('i18n_custom_prompt.name_cannot_be_empty'))
        if not info.prompt or not info.prompt.strip():
            error_messages.append(trans('i18n_custom_prompt.prompt_cannot_be_empty'))
        if not info.type:
            error_messages.append(trans('i18n_custom_prompt.type_cannot_be_empty'))

        specific_ds = info.specific_ds if info.specific_ds is not None else False
        datasource_ids = []
        advanced_application = info.advanced_application

        if specific_ds:
            if info.datasource_names:
                for ds_name in info.datasource_names:
                    if not ds_name or not ds_name.strip():
                        continue
                    if ds_name.strip() in datasource_name_to_id:
                        datasource_ids.append(datasource_name_to_id[ds_name.strip()])
                    else:
                        error_messages.append(
                            trans('i18n_custom_prompt.datasource_not_found').format(ds_name))
            if not datasource_ids and advanced_application is None:
                error_messages.append(trans('i18n_data_training.datasource_assistant_cannot_be_none'))
        else:
            datasource_ids = []
            advanced_application = None

        if error_messages:
            failed_records.append({
                'data': info,
                'errors': error_messages,
            })
            continue

        valid_records.append(CustomPromptInfo(
            name=info.name.strip(),
            prompt=info.prompt.strip() if info.prompt else '',
            type=info.type,
            datasource_ids=datasource_ids,
            datasource_names=info.datasource_names,
            specific_ds=specific_ds,
            advanced_application=advanced_application,
        ))

    for info in valid_records:
        try:
            create_custom_prompt(session, info, oid, trans)
            success_count += 1
        except Exception as e:
            session.rollback()
            failed_records.append({
                'data': info,
                'errors': [str(e)],
            })

    return {
        'success_count': success_count,
        'failed_records': failed_records,
        'duplicate_count': len(duplicate_records),
        'original_count': len(info_list),
        'deduplicated_count': len(deduplicated_list),
    }


def to_xml_string(_dict: list[str] | dict, root: str = 'Other-Infos') -> str:
    def item_name_func(x):
        return 'content' if x == 'Other-Infos' else 'item'

    xml = dict_to_xml(_dict, root_name=root, item_func=item_name_func)
    pretty_xml = parseString(xml).toprettyxml()

    if pretty_xml.startswith('<?xml'):
        end_index = pretty_xml.find('>') + 1
        pretty_xml = pretty_xml[end_index:].lstrip()

    escape_map = {
        '&lt;': '<',
        '&gt;': '>',
        '&amp;': '&',
        '&quot;': '"',
        '&apos;': "'",
    }
    for escaped, original in escape_map.items():
        pretty_xml = pretty_xml.replace(escaped, original)

    return pretty_xml


def find_custom_prompts(session: SessionDep, custom_prompt_type: CustomPromptTypeEnum, oid: int,
                        datasource: int | None = None, advanced_application_id: int | None = None,
                        question: str = '') -> tuple[str, list[str]]:
    # ========= 【改造标记 LLM-CONTEXT-FILTER-NAME】↓ 兼容包装：维持 (Other-Infos XML, 纯正文字符串列表) 契约
    # 日志 end_log(full_message=prompt_list) 与回写 custom_prompt_to_xml 都依赖纯文本元素，
    # 元素类型不得改；需要 name 的调用方（LLM 上下文过滤）走 find_custom_prompt_items =========
    xml, items = find_custom_prompt_items(session, custom_prompt_type, oid, datasource,
                                          advanced_application_id, question)
    return xml, [item['prompt'] for item in items]
    # ========= 【改造标记 LLM-CONTEXT-FILTER-NAME】↑ 兼容包装结束 =========


def find_custom_prompt_items(session: SessionDep, custom_prompt_type: CustomPromptTypeEnum, oid: int,
                             datasource: int | None = None, advanced_application_id: int | None = None,
                             question: str = '') -> tuple[str, list[dict[str, str]]]:
    # ========= 【改造标记 CUSTOM-PROMPT】↓ 旧代码（xpack 版）：按 scope 全量返回，无 question 召回；
    # 本开源版复用改造点1 的 bm25_retrieve，按问题对候选提示词打分取 Top-K =========
    if not oid:
        oid = 1

    candidate_stmt = (
        select(CustomPrompt.id, CustomPrompt.name, CustomPrompt.prompt)
        .where(
            CustomPrompt.oid == oid,
            CustomPrompt.type == custom_prompt_type,
        )
    )
    candidate_params: dict = {}
    if advanced_application_id is not None:
        candidate_stmt = candidate_stmt.where(
            CustomPrompt.advanced_application == advanced_application_id)
    elif datasource is not None:
        candidate_stmt = candidate_stmt.where(
            or_(
                or_(CustomPrompt.specific_ds.is_(False), CustomPrompt.specific_ds.is_(None)),
                and_(
                    CustomPrompt.specific_ds.is_(True),
                    CustomPrompt.datasource_ids.isnot(None),
                    text("datasource_ids @> jsonb_build_array(:datasource)"),
                ),
            )
        )
        candidate_params['datasource'] = datasource
    else:
        candidate_stmt = candidate_stmt.where(
            or_(CustomPrompt.specific_ds.is_(False), CustomPrompt.specific_ds.is_(None)))

    candidate_stmt = candidate_stmt.limit(settings.KEYWORD_RETRIEVAL_MAX_CANDIDATES)

    candidates = session.execute(candidate_stmt, candidate_params).fetchall()

    if settings.KEYWORD_RETRIEVAL_ENABLED:
        matched = bm25_retrieve(
            question, candidates,
            lambda row: row.name)
    else:
        matched = list(candidates)
    # ========= 【改造标记 CUSTOM-PROMPT】↑ 召回逻辑结束 =========

    # ========= 【改造标记 LLM-CONTEXT-FILTER-NAME】↓ 改造点3议题三：结构化返回（name+正文），
    # 供 llm_filter_context 把 BM25 打分依据（name）一并给大模型复核；
    # XML 仍只装正文，保持与 find_custom_prompts 产出完全一致 =========
    items = [{'name': row.name, 'prompt': row.prompt} for row in matched if row.prompt]
    if not items:
        return '', []
    return to_xml_string([item['prompt'] for item in items]), items
    # ========= 【改造标记 LLM-CONTEXT-FILTER-NAME】↑ 结构化返回结束 =========


# ========= 【改造标记 CUSTOM-PROMPT】↑ 新建文件结束 =========
