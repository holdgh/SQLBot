# ========= 【改造标记 METRIC-CENTER】↓ 指标中心 CURD/检索/模板组装（Phase 1，镜像 terminology/curd/terminology.py） =========
import datetime
import traceback
from typing import List, Optional, Any
from xml.dom.minidom import parseString

from sqlalchemy import and_, or_, select, func, delete, update, text, BigInteger

from apps.ai_model.embedding import EmbeddingModelCache
from apps.datasource.models.datasource import CoreDatasource
from apps.metric.models.metric_model import (
    MetricDefinition, MetricAlias, MetricDocument, Dimension,
    MetricDimensionRelation, MetricDependency,
    MetricInfo, MetricInfoResult, DimensionInfo, DimensionInfoResult,
)
from apps.template.generate_chart.generator import get_base_metric_template
from common.core.config import settings
from common.core.deps import SessionDep, Trans
from common.utils.dict_to_xml import dict_to_xml
from common.utils.embedding_threads import run_save_metric_embeddings
# ========= 【改造标记 RAG-KEYWORD】↓ 复用 BM25 关键词检索工具 =========
from common.utils.keyword_retrieval import bm25_retrieve
# ========= 【改造标记 RAG-KEYWORD】↑ 导入结束 =========

METRIC_STATUS_ACTIVE = 'active'
METRIC_STATUS_DISABLED = 'disabled'
METRIC_TYPE_ATOMIC = 'atomic'
METRIC_TYPE_DERIVED = 'derived'
METRIC_TYPE_COMPOSITE = 'composite'
ADDITIVITY_ADDITIVE = 'additive'
ADDITIVITY_SEMI = 'semi'
ADDITIVITY_NON = 'non'


def _scope_ds_condition(model, specific_ds: bool, datasource_ids: Optional[list[int]]):
    """数据源作用域条件（与 terminology 查重规则同构，去掉 advanced_application）"""
    scope_conditions = []

    if not specific_ds:
        scope_conditions.append(
            and_(
                model.specific_ds == True,
                model.datasource_ids.isnot(None),
                func.jsonb_array_length(model.datasource_ids) > 0,
            )
        )
        scope_conditions.append(model.specific_ds == False)
    elif specific_ds and datasource_ids:
        scope_conditions.append(model.specific_ds == False)
        ds_overlap_conditions = [
            model.datasource_ids.contains([ds_id]) for ds_id in datasource_ids
        ]
        scope_conditions.append(
            and_(
                model.specific_ds == True,
                model.datasource_ids.isnot(None),
                or_(*ds_overlap_conditions)
            )
        )
    else:
        scope_conditions.append(
            and_(
                model.specific_ds == True,
                or_(
                    model.datasource_ids.is_(None),
                    func.jsonb_array_length(model.datasource_ids) == 0,
                )
            )
        )

    return or_(*scope_conditions)


def _datasource_filter_condition(model, ds_list: Optional[list[int]]):
    """列表页数据源过滤条件（与 terminology 列表过滤同构）"""
    if ds_list is None or len(ds_list) == 0:
        return None

    datasource_conditions = []
    for ds_id in ds_list:
        datasource_conditions.append(model.datasource_ids.contains([ds_id]))

    return or_(
        model.specific_ds == False,
        and_(model.specific_ds == True, *datasource_conditions)
    )


def build_metric_query(session: SessionDep, oid: int, name: Optional[str] = None,
                       paginate: bool = True, current_page: int = 1, page_size: int = 10,
                       ds_list: Optional[list[int]] = None):
    """构建指标分页/全量查询"""
    base = select(MetricDefinition.id).where(MetricDefinition.oid == oid)

    if name and name.strip() != "":
        base = base.where(MetricDefinition.metric_name.ilike(f"%{name.strip()}%"))

    ds_filter_condition = _datasource_filter_condition(MetricDefinition, ds_list)
    if ds_filter_condition is not None:
        base = base.where(ds_filter_condition)

    count_stmt = select(func.count()).select_from(base.subquery())
    total_count = session.execute(count_stmt).scalar()

    if paginate:
        page_size = max(10, page_size)
        total_pages = (total_count + page_size - 1) // page_size
        current_page = max(1, min(current_page, total_pages)) if total_pages > 0 else 1
        base = (base.order_by(MetricDefinition.create_time.desc())
                .offset((current_page - 1) * page_size).limit(page_size))
    else:
        total_pages = 1
        current_page = 1
        page_size = total_count if total_count > 0 else 1
        base = base.order_by(MetricDefinition.create_time.desc())

    paginated_ids = base.subquery()

    datasource_names_subquery = (
        select(
            func.jsonb_array_elements(MetricDefinition.datasource_ids).cast(BigInteger).label('ds_id'),
            MetricDefinition.id.label('metric_id')
        )
        .where(MetricDefinition.id.in_(paginated_ids))
        .subquery()
    )

    stmt = (
        select(
            MetricDefinition,
            func.jsonb_agg(CoreDatasource.name).filter(CoreDatasource.id.isnot(None)).label('datasource_names'),
        )
        .outerjoin(
            datasource_names_subquery,
            datasource_names_subquery.c.metric_id == MetricDefinition.id
        )
        .outerjoin(
            CoreDatasource,
            CoreDatasource.id == datasource_names_subquery.c.ds_id
        )
        .where(MetricDefinition.id.in_(paginated_ids))
        .group_by(MetricDefinition.id)
        .order_by(MetricDefinition.create_time.desc())
    )

    return stmt, total_count, total_pages, current_page, page_size


def _load_metric_relations(session: SessionDep, rows: list) -> list[MetricInfoResult]:
    """组装别名/维度/依赖，转换为 MetricInfoResult 列表"""
    if not rows:
        return []

    metric_ids = [row.MetricDefinition.id for row in rows]
    _list: list[MetricInfoResult] = []

    alias_map: dict[int, list[str]] = {}
    for row in session.execute(
            select(MetricAlias.metric_id, MetricAlias.alias).where(MetricAlias.metric_id.in_(metric_ids))
    ).all():
        alias_map.setdefault(row.metric_id, []).append(row.alias)

    dimension_map: dict[int, list[dict]] = {}
    dim_rows = session.execute(
        select(MetricDimensionRelation.metric_id, Dimension)
        .join(Dimension, Dimension.id == MetricDimensionRelation.dimension_id)
        .where(MetricDimensionRelation.metric_id.in_(metric_ids), MetricDimensionRelation.enabled.is_(True))
    ).all()
    for row in dim_rows:
        dimension_map.setdefault(row[0], []).append({
            'id': row[1].id,
            'dimension_name': row[1].dimension_name,
            # ========= 【改造标记 METRIC-CENTER】↓ 问题4：default_column 改名 column_name =========
            'column_name': row[1].column_name,
            # ========= 【改造标记 METRIC-CENTER】↑ 问题4 改名结束 =========
            'description': row[1].description,
            'aliases': row[1].aliases if row[1].aliases else [],
        })

    dependency_map: dict[int, list[dict]] = {}
    dep_rows = session.execute(
        select(MetricDependency.derived_metric_id, MetricDependency.expression_hint, MetricDefinition.metric_name)
        .join(MetricDefinition, MetricDefinition.id == MetricDependency.depends_on_metric_id)
        .where(MetricDependency.derived_metric_id.in_(metric_ids))
    ).all()
    for row in dep_rows:
        dependency_map.setdefault(row.derived_metric_id, []).append({
            'depends_on_metric_name': row.metric_name,
            'expression_hint': row.expression_hint,
        })

    for row in rows:
        m: MetricDefinition = row.MetricDefinition
        _list.append(MetricInfoResult(
            id=m.id,
            create_time=m.create_time,
            metric_name=m.metric_name,
            description=m.description,
            business_domain=m.business_domain,
            specific_ds=m.specific_ds if m.specific_ds is not None else False,
            datasource_ids=m.datasource_ids if m.datasource_ids is not None else [],
            datasource_names=row.datasource_names if row.datasource_names is not None else [],
            # ========= 【改造标记 METRIC-CENTER】↓ 问题2方案A：表所属数据源 =========
            source_ds_id=m.source_ds_id,
            # ========= 【改造标记 METRIC-CENTER】↑ 透传结束 =========
            source_table=m.source_table,
            source_column=m.source_column,
            aggregation=m.aggregation,
            filter_rule=m.filter_rule,
            time_field=m.time_field,
            metric_type=m.metric_type or METRIC_TYPE_ATOMIC,
            unit=m.unit,
            normal_range=m.normal_range,
            additivity=m.additivity or ADDITIVITY_ADDITIVE,
            status=m.status or METRIC_STATUS_ACTIVE,
            version=m.version or 1,
            enabled=(m.status or METRIC_STATUS_ACTIVE) == METRIC_STATUS_ACTIVE,
            aliases=alias_map.get(m.id, []),
            dimension_ids=[d['id'] for d in dimension_map.get(m.id, [])],
            dimension_names=[d['dimension_name'] for d in dimension_map.get(m.id, [])],
            dependencies=[{
                'depends_on_metric_name': d['depends_on_metric_name'],
                'expression_hint': d['expression_hint'],
            } for d in dependency_map.get(m.id, [])],
        ))

    return _list


def page_metric(session: SessionDep, current_page: int = 1, page_size: int = 10,
                name: Optional[str] = None, oid: Optional[int] = 1,
                ds_list: Optional[list[int]] = None):
    """分页查询指标"""
    stmt, total_count, total_pages, current_page, page_size = build_metric_query(
        session, oid, name, True, current_page, page_size, ds_list
    )
    rows = session.execute(stmt).all()
    _list = _load_metric_relations(session, rows)

    return current_page, page_size, total_count, total_pages, _list


def get_all_metric(session: SessionDep, name: Optional[str] = None, oid: Optional[int] = 1,
                   ds_list: Optional[list[int]] = None):
    """获取所有指标（不分页）"""
    stmt, total_count, total_pages, current_page, page_size = build_metric_query(
        session, oid, name, False, ds_list=ds_list
    )
    rows = session.execute(stmt).all()
    return _load_metric_relations(session, rows)


def _validate_metric(session: SessionDep, info: MetricInfo, oid: int, trans: Trans, exclude_id: Optional[int] = None):
    if not info.metric_name or not info.metric_name.strip():
        raise Exception(trans("i18n_metric.metric_name_cannot_be_empty"))

    specific_ds = info.specific_ds if info.specific_ds is not None else False
    datasource_ids = info.datasource_ids if info.datasource_ids is not None else []

    metric_type = info.metric_type or METRIC_TYPE_ATOMIC
    if metric_type not in (METRIC_TYPE_ATOMIC, METRIC_TYPE_DERIVED, METRIC_TYPE_COMPOSITE):
        raise Exception(trans("i18n_metric.metric_type_invalid"))

    additivity = info.additivity or ADDITIVITY_ADDITIVE
    if additivity not in (ADDITIVITY_ADDITIVE, ADDITIVITY_SEMI, ADDITIVITY_NON):
        raise Exception(trans("i18n_metric.additivity_invalid"))

    # 作用域查重（oid + metric_name + 数据源作用域）
    query = session.query(MetricDefinition).filter(
        MetricDefinition.metric_name == info.metric_name.strip(),
        MetricDefinition.oid == oid,
    )
    if exclude_id is not None:
        query = query.filter(MetricDefinition.id != exclude_id)

    query = query.filter(_scope_ds_condition(MetricDefinition, specific_ds, datasource_ids))

    if session.query(query.exists()).scalar():
        raise Exception(trans("i18n_metric.exists_in_db"))

    return metric_type, additivity, specific_ds, datasource_ids


def _sync_relations(session: SessionDep, metric_id: int, info: MetricInfo, oid: int,
                    create_time: datetime.datetime):
    """同步别名/关联维度/依赖指标（先删后插）"""
    session.execute(delete(MetricAlias).where(MetricAlias.metric_id == metric_id))
    session.execute(delete(MetricDimensionRelation).where(MetricDimensionRelation.metric_id == metric_id))
    session.execute(delete(MetricDependency).where(MetricDependency.derived_metric_id == metric_id))

    alias_list = []
    seen = set()
    if info.aliases:
        for alias in info.aliases:
            if not alias or not alias.strip():
                continue
            alias = alias.strip()
            if alias in seen:
                continue
            seen.add(alias)
            alias_list.append(MetricAlias(metric_id=metric_id, alias=alias))
    if alias_list:
        session.bulk_save_objects(alias_list)

    if info.dimension_ids:
        relation_list = [
            MetricDimensionRelation(metric_id=metric_id, dimension_id=dim_id, enabled=True)
            for dim_id in info.dimension_ids if dim_id
        ]
        if relation_list:
            session.bulk_save_objects(relation_list)

    if info.dependencies:
        dep_list = []
        for dep in info.dependencies:
            dep_metric_id = dep.depends_on_metric_id
            if dep_metric_id is None and dep.depends_on_metric_name:
                owner = session.execute(
                    select(MetricDefinition.id).where(
                        MetricDefinition.metric_name == dep.depends_on_metric_name.strip(),
                        MetricDefinition.oid == oid,
                    )
                ).scalar()
                dep_metric_id = owner
            if dep_metric_id:
                dep_list.append(MetricDependency(
                    derived_metric_id=metric_id,
                    depends_on_metric_id=dep_metric_id,
                    expression_hint=dep.expression_hint,
                ))
        if dep_list:
            session.bulk_save_objects(dep_list)

    session.flush()


def create_metric(session: SessionDep, info: MetricInfo, oid: int, trans: Trans,
                  skip_embedding: bool = False):
    """创建单个指标记录"""
    metric_type, additivity, specific_ds, datasource_ids = _validate_metric(session, info, oid, trans)

    parent = MetricDefinition(
        metric_name=info.metric_name.strip(),
        create_time=datetime.datetime.now(),
        description=info.description.strip() if info.description else None,
        business_domain=info.business_domain.strip() if info.business_domain else None,
        oid=oid,
        specific_ds=specific_ds,
        datasource_ids=datasource_ids,
        # ========= 【改造标记 METRIC-CENTER】↓ 问题2方案A：表所属数据源 =========
        source_ds_id=info.source_ds_id,
        # ========= 【改造标记 METRIC-CENTER】↑ 落库开始 =========
        source_table=info.source_table.strip() if info.source_table else None,
        source_column=info.source_column.strip() if info.source_column else None,
        aggregation=info.aggregation,
        filter_rule=info.filter_rule.strip() if info.filter_rule else None,
        time_field=info.time_field.strip() if info.time_field else None,
        metric_type=metric_type,
        unit=info.unit.strip() if info.unit else None,
        normal_range=info.normal_range,
        additivity=additivity,
        status=info.status if info.status in (METRIC_STATUS_ACTIVE, METRIC_STATUS_DISABLED) else METRIC_STATUS_ACTIVE,
        version=info.version if info.version and info.version > 0 else 1,
    )
    session.add(parent)
    session.flush()
    session.refresh(parent)

    _sync_relations(session, parent.id, info, oid, datetime.datetime.now())
    session.commit()

    # 口径变更/新建 → 重建检索文档（元数据与检索索引分离）
    rebuild_documents(session, [parent.id])

    if not skip_embedding:
        # save_embeddings 的入参是 metric_document.id（与 run_fill_empty_embeddings 一致）
        doc_ids = session.execute(
            select(MetricDocument.id).where(MetricDocument.metric_id == parent.id)).scalars().all()
        run_save_metric_embeddings(list(doc_ids))

    return parent.id


def update_metric(session: SessionDep, info: MetricInfo, oid: int, trans: Trans):
    count = session.query(MetricDefinition).filter(
        MetricDefinition.oid == oid,
        MetricDefinition.id == info.id
    ).count()
    if count == 0:
        raise Exception(trans('i18n_metric.metric_not_exists'))

    metric_type, additivity, specific_ds, datasource_ids = _validate_metric(
        session, info, oid, trans, exclude_id=info.id
    )

    current = session.query(MetricDefinition).filter(MetricDefinition.id == info.id).first()

    stmt = update(MetricDefinition).where(MetricDefinition.id == info.id).values(
        metric_name=info.metric_name.strip(),
        description=info.description.strip() if info.description else None,
        business_domain=info.business_domain.strip() if info.business_domain else None,
        specific_ds=specific_ds,
        datasource_ids=datasource_ids,
        # ========= 【改造标记 METRIC-CENTER】↓ 问题2方案A：表所属数据源 =========
        source_ds_id=info.source_ds_id,
        # ========= 【改造标记 METRIC-CENTER】↑ 落库开始 =========
        source_table=info.source_table.strip() if info.source_table else None,
        source_column=info.source_column.strip() if info.source_column else None,
        aggregation=info.aggregation,
        filter_rule=info.filter_rule.strip() if info.filter_rule else None,
        time_field=info.time_field.strip() if info.time_field else None,
        metric_type=metric_type,
        unit=info.unit.strip() if info.unit else None,
        normal_range=info.normal_range,
        additivity=additivity,
        status=info.status if info.status in (METRIC_STATUS_ACTIVE, METRIC_STATUS_DISABLED) else METRIC_STATUS_ACTIVE,
        # 口径变更 → 版本号 +1，便于追溯当时口径（规则 G3）
        version=(current.version or 1) + 1,
    )
    session.execute(stmt)

    _sync_relations(session, info.id, info, oid, datetime.datetime.now())
    session.commit()

    rebuild_documents(session, [info.id])
    doc_ids = session.execute(
        select(MetricDocument.id).where(MetricDocument.metric_id == info.id)).scalars().all()
    run_save_metric_embeddings(list(doc_ids))

    return info.id


def delete_metric(session: SessionDep, ids: list[int], oid: int):
    session.execute(delete(MetricAlias).where(MetricAlias.metric_id.in_(ids)))
    session.execute(delete(MetricDocument).where(MetricDocument.metric_id.in_(ids)))
    session.execute(delete(MetricDimensionRelation).where(MetricDimensionRelation.metric_id.in_(ids)))
    session.execute(delete(MetricDependency).where(
        or_(MetricDependency.derived_metric_id.in_(ids), MetricDependency.depends_on_metric_id.in_(ids))))
    stmt = delete(MetricDefinition).where(
        and_(MetricDefinition.oid == oid, MetricDefinition.id.in_(ids)))
    session.execute(stmt)
    session.commit()


def enable_metric(session: SessionDep, id: int, enabled: bool, trans: Trans, oid: int):
    count = session.query(MetricDefinition).filter(
        MetricDefinition.id == id,
        MetricDefinition.oid == oid,
    ).count()
    if count == 0:
        raise Exception(trans('i18n_metric.metric_not_exists'))

    stmt = update(MetricDefinition).where(
        and_(MetricDefinition.oid == oid, MetricDefinition.id == id)).values(
        status=METRIC_STATUS_ACTIVE if enabled else METRIC_STATUS_DISABLED,
    )
    session.execute(stmt)
    session.commit()


# ---------- 维度（dimension）管理 ----------

def list_dimension(session: SessionDep, oid: Optional[int] = 1, name: Optional[str] = None) -> List[DimensionInfoResult]:
    stmt = select(Dimension).where(Dimension.oid == oid)
    if name and name.strip() != "":
        stmt = stmt.where(Dimension.dimension_name.ilike(f"%{name.strip()}%"))
    stmt = stmt.order_by(Dimension.create_time.desc())

    _list: List[DimensionInfoResult] = []
    for dim in session.execute(stmt).scalars().all():
        metric_count = session.execute(
            select(func.count()).select_from(
                select(MetricDimensionRelation.id)
                .join(MetricDefinition, MetricDefinition.id == MetricDimensionRelation.metric_id)
                .where(MetricDimensionRelation.dimension_id == dim.id,
                       MetricDimensionRelation.enabled.is_(True),
                       MetricDefinition.oid == oid)
                .subquery()
            )
        ).scalar()
        _list.append(DimensionInfoResult(
            id=dim.id,
            create_time=dim.create_time,
            dimension_name=dim.dimension_name,
            aliases=dim.aliases if dim.aliases else [],
            # ========= 【改造标记 METRIC-CENTER】↓ 问题4：维度落点三元组透传 =========
            source_ds_id=dim.source_ds_id,
            source_table=dim.source_table,
            column_name=dim.column_name,
            # ========= 【改造标记 METRIC-CENTER】↑ 问题4 透传结束（原 default_column） =========
            description=dim.description,
            metric_count=metric_count or 0,
        ))
    return _list


def create_dimension(session: SessionDep, info: DimensionInfo, oid: int, trans: Trans) -> int:
    if not info.dimension_name or not info.dimension_name.strip():
        raise Exception(trans("i18n_metric.dimension_name_cannot_be_empty"))

    exists = session.query(Dimension).filter(
        Dimension.oid == oid,
        Dimension.dimension_name == info.dimension_name.strip(),
    ).count()
    if exists > 0:
        raise Exception(trans("i18n_metric.dimension_exists_in_db"))

    dim = Dimension(
        dimension_name=info.dimension_name.strip(),
        create_time=datetime.datetime.now(),
        oid=oid,
        aliases=[a.strip() for a in (info.aliases or []) if a and a.strip()],
        # ========= 【改造标记 METRIC-CENTER】↓ 问题4：落点三元组落库 =========
        source_ds_id=info.source_ds_id,
        source_table=info.source_table.strip() if info.source_table else None,
        column_name=info.column_name.strip() if info.column_name else None,
        # ========= 【改造标记 METRIC-CENTER】↑ 问题4 落库结束（原 default_column） =========
        description=info.description.strip() if info.description else None,
    )
    session.add(dim)
    session.commit()
    session.refresh(dim)
    return dim.id


def update_dimension(session: SessionDep, info: DimensionInfo, oid: int, trans: Trans) -> int:
    count = session.query(Dimension).filter(Dimension.oid == oid, Dimension.id == info.id).count()
    if count == 0:
        raise Exception(trans('i18n_metric.dimension_not_exists'))

    exists = session.query(Dimension).filter(
        Dimension.oid == oid,
        Dimension.dimension_name == info.dimension_name.strip(),
        Dimension.id != info.id,
    ).count()
    if exists > 0:
        raise Exception(trans("i18n_metric.dimension_exists_in_db"))

    stmt = update(Dimension).where(Dimension.id == info.id).values(
        dimension_name=info.dimension_name.strip(),
        aliases=[a.strip() for a in (info.aliases or []) if a and a.strip()],
        # ========= 【改造标记 METRIC-CENTER】↓ 问题4：落点三元组更新 =========
        source_ds_id=info.source_ds_id,
        source_table=info.source_table.strip() if info.source_table else None,
        column_name=info.column_name.strip() if info.column_name else None,
        # ========= 【改造标记 METRIC-CENTER】↑ 问题4 更新结束（原 default_column） =========
        description=info.description.strip() if info.description else None,
    )
    session.execute(stmt)
    session.commit()
    return info.id


def delete_dimension(session: SessionDep, ids: list[int], oid: int):
    session.execute(delete(MetricDimensionRelation).where(MetricDimensionRelation.dimension_id.in_(ids)))
    session.execute(delete(Dimension).where(and_(Dimension.oid == oid, Dimension.id.in_(ids))))
    session.commit()


# ---------- 检索文档（元数据与检索索引分离） ----------

def rebuild_documents(session: SessionDep, metric_ids: List[int]):
    """由 metric_definition + metric_alias + 关联维度组装 document_text，整条重建。"""
    if not metric_ids:
        return

    for metric_id in metric_ids:
        m = session.query(MetricDefinition).filter(MetricDefinition.id == metric_id).first()
        if m is None:
            continue

        aliases = [row.alias for row in session.execute(
            select(MetricAlias.alias).where(MetricAlias.metric_id == metric_id)).all()]

        dimension_names = [row.dimension_name for row in session.execute(
            select(Dimension.dimension_name)
            .join(MetricDimensionRelation, MetricDimensionRelation.dimension_id == Dimension.id)
            .where(MetricDimensionRelation.metric_id == metric_id,
                   MetricDimensionRelation.enabled.is_(True))).all()]

        dependency_names = [row.metric_name for row in session.execute(
            select(MetricDefinition.metric_name)
            .join(MetricDependency, MetricDependency.depends_on_metric_id == MetricDefinition.id)
            .where(MetricDependency.derived_metric_id == metric_id)).all()]

        parts = [
            f"指标名称: {m.metric_name}",
            f"指标定义: {m.description}" if m.description else "",
            f"业务域: {m.business_domain}" if m.business_domain else "",
            f"别名: {'、'.join(aliases)}" if aliases else "",
            f"指标类型: {m.metric_type or METRIC_TYPE_ATOMIC}",
            f"聚合方式: {m.aggregation}" if m.aggregation else "",
            f"过滤规则: {m.filter_rule}" if m.filter_rule else "",
            f"时间字段: {m.time_field}" if m.time_field else "",
            f"单位: {m.unit}" if m.unit else "",
            f"来源表: {m.source_table}" if m.source_table else "",
            f"来源字段: {m.source_column}" if m.source_column else "",
            f"支持维度: {'、'.join(dimension_names)}" if dimension_names else "",
            f"依赖指标: {'、'.join(dependency_names)}" if dependency_names else "",
        ]
        document_text = "\n".join([p for p in parts if p])

        existing = session.execute(
            select(MetricDocument).where(MetricDocument.metric_id == metric_id)).scalar_one_or_none()
        if existing is None:
            session.add(MetricDocument(metric_id=metric_id, document_text=document_text))
        else:
            existing.document_text = document_text
            # 口径变更 → embedding 置空待重建
            existing.embedding = None
        session.flush()

    session.commit()


def run_fill_empty_embeddings(session_maker):
    """补齐空 embedding（对 metric_document.document_text）"""
    try:
        if not settings.EMBEDDING_ENABLED:
            return
        session = session_maker()
        results = session.execute(
            select(MetricDocument.id).where(MetricDocument.embedding.is_(None))).scalars().all()
        save_embeddings(session_maker, results)
    except Exception:
        traceback.print_exc()
    finally:
        session_maker.remove()


def save_embeddings(session_maker, ids: List[int]):
    if not settings.EMBEDDING_ENABLED:
        return
    if not ids or len(ids) == 0:
        return
    try:
        session = session_maker()
        _list = session.query(MetricDocument).filter(MetricDocument.id.in_(ids)).all()
        _docs = [item.document_text or "" for item in _list]
        if not _docs:
            return

        model = EmbeddingModelCache.get_model()
        results = model.embed_documents(_docs)

        for index in range(len(results)):
            stmt = update(MetricDocument).where(MetricDocument.id == _list[index].id).values(
                embedding=results[index])
            session.execute(stmt)
            session.commit()
    except Exception:
        traceback.print_exc()
    finally:
        session_maker.remove()


metric_embedding_sql = f"""
SELECT metric_id, document_text, similarity
FROM
(SELECT d.metric_id, d.document_text, m.oid, m.specific_ds, m.datasource_ids, m.status,
( 1 - (d.embedding <=> :embedding_array) ) AS similarity
FROM metric_document AS d
INNER JOIN metric_definition AS m ON m.id = d.metric_id
) TEMP
WHERE similarity > {settings.EMBEDDING_METRIC_SIMILARITY} AND oid = :oid AND status = 'active'
AND (specific_ds = false OR specific_ds IS NULL)
ORDER BY similarity DESC
LIMIT {settings.EMBEDDING_METRIC_TOP_COUNT}
"""

metric_embedding_sql_with_datasource = f"""
SELECT metric_id, document_text, similarity
FROM
(SELECT d.metric_id, d.document_text, m.oid, m.specific_ds, m.datasource_ids, m.status,
( 1 - (d.embedding <=> :embedding_array) ) AS similarity
FROM metric_document AS d
INNER JOIN metric_definition AS m ON m.id = d.metric_id
) TEMP
WHERE similarity > {settings.EMBEDDING_METRIC_SIMILARITY} AND oid = :oid AND status = 'active'
AND (
    (specific_ds = false OR specific_ds IS NULL)
     OR
    (specific_ds = true AND datasource_ids IS NOT NULL AND datasource_ids @> jsonb_build_array(:datasource))
)
ORDER BY similarity DESC
LIMIT {settings.EMBEDDING_METRIC_TOP_COUNT}
"""


def select_metric_by_question(session: SessionDep, question: str, oid: int, datasource: int = None) -> list[dict]:
    """BM25（指标名/别名）+ pgvector（检索文档）混合召回，按 oid + 数据源隔离。"""
    if not question or question.strip() == "":
        return []

    _ids: list[int] = []
    _ordered: list[int] = []

    # ---- BM25 候选：指标名 + 别名（按 oid + 数据源 + 启用状态过滤） ----
    if settings.KEYWORD_RETRIEVAL_ENABLED:
        base_filter = [
            MetricDefinition.oid == oid,
            MetricDefinition.status == METRIC_STATUS_ACTIVE,
        ]
        if datasource is not None:
            base_filter.append(or_(
                or_(MetricDefinition.specific_ds.is_(False), MetricDefinition.specific_ds.is_(None)),
                and_(
                    MetricDefinition.specific_ds.is_(True),
                    MetricDefinition.datasource_ids.isnot(None),
                    text("metric_definition.datasource_ids @> jsonb_build_array(:datasource)")
                ),
            ))
        else:
            base_filter.append(or_(MetricDefinition.specific_ds.is_(False), MetricDefinition.specific_ds.is_(None)))

        params: dict[str, Any] = {}
        if datasource is not None:
            params['datasource'] = datasource

        name_rows = session.execute(
            select(MetricDefinition.id, MetricDefinition.metric_name)
            .where(*base_filter)
            .limit(settings.KEYWORD_RETRIEVAL_MAX_CANDIDATES),
            params
        ).all()

        alias_rows = session.execute(
            select(MetricDefinition.id, MetricAlias.alias)
            .join(MetricAlias, MetricAlias.metric_id == MetricDefinition.id)
            .where(*base_filter)
            .limit(settings.KEYWORD_RETRIEVAL_MAX_CANDIDATES),
            params
        ).all()

        # 同一指标的名称与别名合并为一条文档参与 BM25 打分
        text_map: dict[int, str] = {}
        for row in name_rows:
            text_map[row.id] = row.metric_name or ""
        for row in alias_rows:
            text_map[row.id] = (text_map.get(row.id, "") + " " + (row.alias or "")).strip()

        documents = [{'id': _id, 'text': _text} for _id, _text in text_map.items()]
        for doc in bm25_retrieve(question, documents, lambda row: row['text']):
            if doc['id'] not in _ordered:
                _ordered.append(doc['id'])

    # ---- pgvector 召回检索文档 ----
    if settings.EMBEDDING_ENABLED:
        with session.begin_nested():
            try:
                model = EmbeddingModelCache.get_model()
                embedding = model.embed_query(question)

                if datasource is not None:
                    results = session.execute(text(metric_embedding_sql_with_datasource),
                                              {'embedding_array': str(embedding), 'oid': oid,
                                               'datasource': datasource}).fetchall()
                else:
                    results = session.execute(text(metric_embedding_sql),
                                              {'embedding_array': str(embedding), 'oid': oid}).fetchall()

                for row in results:
                    if row.metric_id not in _ordered:
                        _ordered.append(row.metric_id)

            except Exception:
                traceback.print_exc()
                session.rollback()

    if len(_ordered) == 0:
        return []

    # ---- 加载指标全量信息（含别名/维度/依赖），保持召回顺序 ----
    rows = session.execute(
        select(MetricDefinition).where(MetricDefinition.id.in_(_ordered))
    ).scalars().all()
    order_map = {mid: i for i, mid in enumerate(_ordered)}
    rows = sorted(rows, key=lambda m: order_map.get(m.id, 999999))

    metrics: list[dict] = []
    for m in rows:
        aliases = [r.alias for r in session.execute(
            select(MetricAlias.alias).where(MetricAlias.metric_id == m.id)).all()]

        dimensions = []
        for row in session.execute(
                select(Dimension)
                .join(MetricDimensionRelation, MetricDimensionRelation.dimension_id == Dimension.id)
                .where(MetricDimensionRelation.metric_id == m.id,
                       MetricDimensionRelation.enabled.is_(True))).scalars().all():
            dimensions.append({
                'dimension_name': row.dimension_name,
                # ========= 【改造标记 METRIC-CENTER】↓ 问题4：default_column 改名 column_name =========
                'column_name': row.column_name,
                # ========= 【改造标记 METRIC-CENTER】↑ 问题4 改名结束 =========
                'description': row.description,
            })

        dependencies = []
        for row in session.execute(
                select(MetricDefinition.metric_name, MetricDependency.expression_hint)
                .join(MetricDependency, MetricDependency.depends_on_metric_id == MetricDefinition.id)
                .where(MetricDependency.derived_metric_id == m.id)).all():
            dependencies.append({
                'depends_on_metric_name': row.metric_name,
                'expression_hint': row.expression_hint,
            })

        metrics.append({
            'metric_name': m.metric_name,
            'metric_type': m.metric_type or METRIC_TYPE_ATOMIC,
            'description': m.description or '',
            'business_domain': m.business_domain or '',
            'aggregation': m.aggregation or '',
            'filter_rule': m.filter_rule or '',
            'time_field': m.time_field or '',
            'unit': m.unit or '',
            'normal_range': m.normal_range if m.normal_range else '',
            'additivity': m.additivity or ADDITIVITY_ADDITIVE,
            'source_table': m.source_table or '',
            'source_column': m.source_column or '',
            'aliases': aliases,
            'dimensions': dimensions,
            'dependencies': dependencies,
        })

    return metrics


def to_xml_string(_dict: list[dict] | dict, root: str = 'metrics') -> str:
    item_name_map = {
        'metrics': 'metric',
        'aliases': 'alias',
        'dimensions': 'dimension',
        'dependencies': 'dependency',
    }
    item_name_func = lambda x: item_name_map.get(x, 'item')
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
        '&apos;': "'"
    }
    for escaped, original in escape_map.items():
        pretty_xml = pretty_xml.replace(escaped, original)

    return pretty_xml


def get_metric_template(session: SessionDep, question: str, oid: Optional[int] = 1,
                        datasource: Optional[int] = None) -> tuple[str, list[dict]]:
    """召回指标 → 组装提示词指标块；召回为空返回 ('', [])。"""
    if not oid:
        oid = 1
    _results = select_metric_by_question(session, question, oid, datasource)
    if _results and len(_results) > 0:
        metrics = to_xml_string(_results, 'metrics')
        template = get_base_metric_template().format(metrics=metrics)
        return template, _results
    else:
        return '', []
# ========= 【改造标记 METRIC-CENTER】↑ 指标中心 CURD 结束 =========
