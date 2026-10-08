# ========= 【改造标记 CUSTOM-PROMPT】↓ 开源自定义提示词 API，路由与 sqlbot_xpack 闭源版完全一致（前端 prompt.ts 契约，新建文件） =========
import asyncio
import hashlib
import io
import os
import uuid

import pandas as pd
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlmodel import Session

from apps.chat.models.chat_model import AxisObj
from apps.custom_prompt.curd.custom_prompt import (
    batch_create_custom_prompt,
    create_custom_prompt,
    delete_custom_prompt,
    get_all_custom_prompt,
    page_custom_prompt,
    update_custom_prompt,
)
from apps.custom_prompt.models.custom_prompt_model import (
    CustomPrompt,
    CustomPromptInfo,
    CustomPromptInfoResult,
    CustomPromptTypeEnum,
    SearchCustomPromptInfo,
)
from apps.datasource.models.datasource import CoreDatasource
from apps.swagger.i18n import PLACEHOLDER_PREFIX
from apps.system.models.system_model import AssistantModel
from common.audit.models.log_model import OperationModules, OperationType
from common.audit.schemas.logger_decorator import LogConfig, system_log
from common.core.config import settings
from common.core.db import engine
from common.core.deps import CurrentUser, SessionDep, Trans
from common.utils.data_format import DataFormat
from common.utils.excel import get_excel_column_count

router = APIRouter(tags=["CustomPrompt"], prefix="/system/custom_prompt")

path = settings.EXCEL_PATH
session_maker = scoped_session(sessionmaker(bind=engine, class_=Session))


@router.post("/{custom_prompt_type}/page/{current_page}/{page_size}",
             summary=f"{PLACEHOLDER_PREFIX}custom_prompt_page")
async def pager(session: SessionDep, current_user: CurrentUser, current_page: int, page_size: int,
                custom_prompt_type: CustomPromptTypeEnum,
                search_obj: SearchCustomPromptInfo | None = None):
    name = search_obj.name if search_obj else None
    ds_list = search_obj.ds_list if search_obj else None
    adv_list = search_obj.adv_list if search_obj else None

    current_page, page_size, total_count, total_pages, _list = page_custom_prompt(
        session, custom_prompt_type, current_page, page_size, name, current_user.oid, ds_list, adv_list)

    return {
        "current_page": current_page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "data": _list,
    }


@router.put("", summary=f"{PLACEHOLDER_PREFIX}create_or_update_custom_prompt")
@system_log(LogConfig(operation_type=OperationType.CREATE_OR_UPDATE, module=OperationModules.PROMPT_WORDS,
                      resource_id_expr='info.id', result_id_expr="result_self"))
async def create_or_update(session: SessionDep, current_user: CurrentUser, trans: Trans,
                           info: CustomPromptInfo):
    oid = current_user.oid
    if info.id:
        return update_custom_prompt(session, info, oid, trans)
    else:
        return create_custom_prompt(session, info, oid, trans)


@router.delete("", summary=f"{PLACEHOLDER_PREFIX}delete_custom_prompt")
@system_log(LogConfig(operation_type=OperationType.DELETE, module=OperationModules.PROMPT_WORDS,
                      resource_id_expr='id_list'))
async def delete(session: SessionDep, current_user: CurrentUser, id_list: list[int]):
    oid = current_user.oid
    delete_custom_prompt(session, id_list, oid)


@router.post("/{custom_prompt_type}/export", summary=f"{PLACEHOLDER_PREFIX}export_custom_prompt")
@system_log(LogConfig(operation_type=OperationType.EXPORT, module=OperationModules.PROMPT_WORDS))
async def export_excel(session: SessionDep, trans: Trans, current_user: CurrentUser,
                       custom_prompt_type: CustomPromptTypeEnum,
                       search_obj: SearchCustomPromptInfo | None = None):
    name = search_obj.name if search_obj else None
    ds_list = search_obj.ds_list if search_obj else None
    adv_list = search_obj.adv_list if search_obj else None

    def inner():
        _list = get_all_custom_prompt(session, custom_prompt_type, name, current_user.oid, ds_list, adv_list)

        data_list = []
        for obj in _list:
            _data = {
                "name": obj.name,
                "prompt": obj.prompt,
                "all_data_sources": 'N' if obj.specific_ds else 'Y',
                "datasource": ', '.join(obj.datasource_names) if obj.datasource_names and obj.specific_ds else '',
            }
            data_list.append(_data)

        fields = []
        fields.append(AxisObj(name=trans('i18n_custom_prompt.prompt_word_name'), value='name'))
        fields.append(AxisObj(name=trans('i18n_custom_prompt.prompt_word_content'), value='prompt'))
        fields.append(AxisObj(name=trans('i18n_custom_prompt.effective_data_sources'), value='datasource'))
        fields.append(AxisObj(name=trans('i18n_custom_prompt.all_data_sources'), value='all_data_sources'))

        md_data, _fields_list = DataFormat.convert_object_array_for_pandas(fields, data_list)

        df = pd.DataFrame(md_data, columns=_fields_list)

        buffer = io.BytesIO()

        with pd.ExcelWriter(buffer, engine='xlsxwriter',
                            engine_kwargs={'options': {'strings_to_numbers': False}}) as writer:
            df.to_excel(writer, sheet_name='Sheet1', index=False)

        buffer.seek(0)
        return io.BytesIO(buffer.getvalue())

    result = await asyncio.to_thread(inner)
    return StreamingResponse(result, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/template", summary=f"{PLACEHOLDER_PREFIX}excel_template_custom_prompt")
async def excel_template(trans: Trans):
    def inner():
        data_list = [{
            "name": trans('i18n_custom_prompt.prompt_word_name_template_example1'),
            "prompt": trans('i18n_custom_prompt.prompt_word_content_template_example1'),
            "datasource": trans('i18n_custom_prompt.effective_data_sources_template_example1'),
            "all_data_sources": 'N',
        }, {
            "name": trans('i18n_custom_prompt.prompt_word_name_template_example2'),
            "prompt": trans('i18n_custom_prompt.prompt_word_content_template_example2'),
            "datasource": '',
            "all_data_sources": 'Y',
        }]

        fields = []
        fields.append(AxisObj(name=trans('i18n_custom_prompt.prompt_word_name_template'), value='name'))
        fields.append(AxisObj(name=trans('i18n_custom_prompt.prompt_word_content_template'), value='prompt'))
        fields.append(AxisObj(name=trans('i18n_custom_prompt.effective_data_sources_template'), value='datasource'))
        fields.append(AxisObj(name=trans('i18n_custom_prompt.all_data_sources_template'), value='all_data_sources'))

        md_data, _fields_list = DataFormat.convert_object_array_for_pandas(fields, data_list)

        df = pd.DataFrame(md_data, columns=_fields_list)

        buffer = io.BytesIO()

        with pd.ExcelWriter(buffer, engine='xlsxwriter',
                            engine_kwargs={'options': {'strings_to_numbers': False}}) as writer:
            df.to_excel(writer, sheet_name='Sheet1', index=False)

        buffer.seek(0)
        return io.BytesIO(buffer.getvalue())

    result = await asyncio.to_thread(inner)
    return StreamingResponse(result, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/{custom_prompt_type}/uploadExcel", summary=f"{PLACEHOLDER_PREFIX}upload_custom_prompt")
@system_log(LogConfig(operation_type=OperationType.IMPORT, module=OperationModules.PROMPT_WORDS))
async def upload_excel(trans: Trans, current_user: CurrentUser,
                       custom_prompt_type: CustomPromptTypeEnum, file: UploadFile = File(...)):
    ALLOWED_EXTENSIONS = {"xlsx", "xls"}
    if not file.filename.lower().endswith(tuple(ALLOWED_EXTENSIONS)):
        raise Exception("Only support .xlsx/.xls")

    os.makedirs(path, exist_ok=True)
    # Strip any directory components from the client-supplied filename to
    # prevent path traversal (CWE-22).
    safe_name = os.path.basename(file.filename)
    name_root, name_ext = os.path.splitext(safe_name)
    base_filename = f"{name_root}_{hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:10]}"
    filename = f"{base_filename}{name_ext}"
    save_path = os.path.realpath(os.path.join(path, filename))
    if os.path.commonpath([save_path, os.path.realpath(path)]) != os.path.realpath(path):
        raise Exception("Invalid filename")
    with open(save_path, "wb") as f:
        f.write(await file.read())

    oid = current_user.oid

    use_cols = [0, 1, 2, 3]

    def inner():
        session = session_maker()

        sheet_names = pd.ExcelFile(save_path).sheet_names

        import_data = []

        for sheet_name in sheet_names:
            if get_excel_column_count(save_path, sheet_name) < len(use_cols):
                raise Exception(trans("i18n_excel_import.col_num_not_match"))

            df = pd.read_excel(
                save_path,
                sheet_name=sheet_name,
                engine='calamine',
                header=0,
                usecols=use_cols,
                dtype=str,
            ).fillna("")

            for _, row in df.iterrows():
                if row.isnull().all():
                    continue

                name = row[0].strip() if pd.notna(row[0]) and row[0].strip() else ''
                prompt = row[1].strip() if pd.notna(row[1]) else ''
                datasource_names = [d.strip() for d in row[2].strip().split(',')] if pd.notna(row[2]) and row[
                    2].strip() else []
                all_datasource = True if pd.notna(row[3]) and row[3].lower().strip() in ['y', 'yes', 'true'] else False
                specific_ds = False if all_datasource else True

                import_data.append(CustomPromptInfo(
                    name=name,
                    prompt=prompt,
                    datasource_names=datasource_names,
                    specific_ds=specific_ds,
                    type=custom_prompt_type,
                ))

        res = batch_create_custom_prompt(session, import_data, oid, trans)

        failed_records = res['failed_records']

        error_excel_filename = None

        if len(failed_records) > 0:
            data_list = []
            for obj in failed_records:
                _data = {
                    "name": obj['data'].name,
                    "prompt": obj['data'].prompt,
                    "all_data_sources": 'N' if obj['data'].specific_ds else 'Y',
                    "datasource": ', '.join(obj['data'].datasource_names) if obj['data'].datasource_names and obj[
                        'data'].specific_ds else '',
                    "errors": ', '.join(obj['errors']),
                }
                data_list.append(_data)

            fields = []
            fields.append(AxisObj(name=trans('i18n_custom_prompt.prompt_word_name'), value='name'))
            fields.append(AxisObj(name=trans('i18n_custom_prompt.prompt_word_content'), value='prompt'))
            fields.append(AxisObj(name=trans('i18n_custom_prompt.effective_data_sources'), value='datasource'))
            fields.append(AxisObj(name=trans('i18n_custom_prompt.all_data_sources'), value='all_data_sources'))
            fields.append(AxisObj(name=trans('i18n_data_training.error_info'), value='errors'))

            md_data, _fields_list = DataFormat.convert_object_array_for_pandas(fields, data_list)

            df = pd.DataFrame(md_data, columns=_fields_list)
            error_excel_filename = f"{base_filename}_error.xlsx"
            save_error_path = os.path.realpath(os.path.join(path, error_excel_filename))
            if os.path.commonpath([save_error_path, os.path.realpath(path)]) != os.path.realpath(path):
                raise Exception("Invalid filename")
            df.to_excel(save_error_path, index=False)

        return {
            'success_count': res['success_count'],
            'failed_count': len(failed_records),
            'duplicate_count': res['duplicate_count'],
            'original_count': res['original_count'],
            'error_excel_filename': error_excel_filename,
        }

    return await asyncio.to_thread(inner)


# ========= 【改造标记 CUSTOM-PROMPT】↓ 新增前端 promptApi.getOne 契约路由（须注册在 GET /template 之后） =========
@router.get("/{id:int}", summary="Get Custom Prompt by Id")
async def get_one(session: SessionDep, current_user: CurrentUser, id: int):
    row = session.get(CustomPrompt, id)
    if row is None or row.oid != current_user.oid:
        raise Exception("i18n_custom_prompt.not_exists")

    datasource_names = []
    if row.datasource_ids:
        datasource_stmt = select(CoreDatasource.name).where(CoreDatasource.id.in_(row.datasource_ids))
        datasource_names = [ds_name for (ds_name,) in session.execute(datasource_stmt).all()]

    advanced_application_name = None
    if row.advanced_application:
        assistant_stmt = select(AssistantModel.name).where(
            AssistantModel.id == row.advanced_application, AssistantModel.type == 1)
        assistant_row = session.execute(assistant_stmt).first()
        advanced_application_name = assistant_row[0] if assistant_row else None

    return CustomPromptInfoResult(
        id=row.id,
        oid=row.oid,
        type=row.type,
        create_time=row.create_time,
        name=row.name,
        prompt=row.prompt,
        specific_ds=row.specific_ds if row.specific_ds is not None else False,
        datasource_ids=row.datasource_ids if row.datasource_ids is not None else [],
        datasource_names=datasource_names,
        advanced_application=str(row.advanced_application) if row.advanced_application else None,
        advanced_application_name=advanced_application_name,
    )
# ========= 【改造标记 CUSTOM-PROMPT】↑ get_one 路由结束 =========
# ========= 【改造标记 CUSTOM-PROMPT】↑ 新建文件结束 =========
