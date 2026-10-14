# ========= 【改造标记 METRIC-CENTER】↓ 指标中心 API（Phase 1，镜像 terminology/api，裁剪 export/uploadExcel） =========
from typing import Optional

from fastapi import APIRouter, Query

from apps.metric.curd.metric import (
    page_metric, create_metric, update_metric, delete_metric, enable_metric,
    list_dimension, create_dimension, update_dimension, delete_dimension,
)
from apps.metric.models.metric_model import MetricInfo, DimensionInfo
from apps.swagger.i18n import PLACEHOLDER_PREFIX
from apps.system.schemas.permission import SqlbotPermission, require_permissions
from common.core.deps import SessionDep, CurrentUser, Trans
from common.audit.models.log_model import OperationType, OperationModules
from common.audit.schemas.logger_decorator import LogConfig, system_log

router = APIRouter(tags=["Metric"], prefix="/system/metric")


@router.get("/page/{current_page}/{page_size}", summary=f"{PLACEHOLDER_PREFIX}get_metric_page")
@require_permissions(permission=SqlbotPermission(role=['ws_admin']))
async def pager(session: SessionDep, current_user: CurrentUser, current_page: int, page_size: int,
                name: Optional[str] = Query(None, description="搜索指标(可选)"),
                ds_list: Optional[list[int]] = Query(None, description="数据源ID集合(可选)")):
    current_page, page_size, total_count, total_pages, _list = page_metric(
        session, current_page, page_size, name, current_user.oid, ds_list)

    return {
        "current_page": current_page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "data": _list
    }


@router.put("", summary=f"{PLACEHOLDER_PREFIX}create_or_update_metric")
@require_permissions(permission=SqlbotPermission(role=['ws_admin'], type='ds', keyExpression="info.datasource_ids"))
@system_log(LogConfig(operation_type=OperationType.CREATE_OR_UPDATE, module=OperationModules.METRIC,
                      resource_id_expr='info.id', result_id_expr="result_self"))
async def create_or_update(session: SessionDep, current_user: CurrentUser, trans: Trans, info: MetricInfo):
    oid = current_user.oid
    if info.id:
        return update_metric(session, info, oid, trans)
    else:
        return create_metric(session, info, oid, trans)


@router.delete("", summary=f"{PLACEHOLDER_PREFIX}delete_metric")
@system_log(LogConfig(operation_type=OperationType.DELETE, module=OperationModules.METRIC, resource_id_expr='id_list'))
@require_permissions(permission=SqlbotPermission(role=['ws_admin']))
async def delete(session: SessionDep, current_user: CurrentUser, id_list: list[int]):
    oid = current_user.oid
    delete_metric(session, id_list, oid)


@router.get("/{id}/enable/{enabled}", summary=f"{PLACEHOLDER_PREFIX}enable_metric")
@system_log(LogConfig(operation_type=OperationType.UPDATE, module=OperationModules.METRIC, resource_id_expr='id'))
@require_permissions(permission=SqlbotPermission(role=['ws_admin']))
async def enable(session: SessionDep, current_user: CurrentUser, id: int, enabled: bool, trans: Trans):
    oid = current_user.oid
    enable_metric(session, id, enabled, trans, oid)


# ---------- 维度管理（同页 tab 形态） ----------

@router.get("/dimension/list", summary=f"{PLACEHOLDER_PREFIX}get_dimension_list")
@require_permissions(permission=SqlbotPermission(role=['ws_admin']))
async def dimension_list(session: SessionDep, current_user: CurrentUser,
                         name: Optional[str] = Query(None, description="搜索维度(可选)")):
    return list_dimension(session, current_user.oid, name)


@router.put("/dimension", summary=f"{PLACEHOLDER_PREFIX}create_or_update_dimension")
@require_permissions(permission=SqlbotPermission(role=['ws_admin']))
@system_log(LogConfig(operation_type=OperationType.CREATE_OR_UPDATE, module=OperationModules.METRIC,
                      resource_id_expr='info.id', result_id_expr="result_self"))
async def create_or_update_dimension(session: SessionDep, current_user: CurrentUser, trans: Trans,
                                     info: DimensionInfo):
    oid = current_user.oid
    if info.id:
        return update_dimension(session, info, oid, trans)
    else:
        return create_dimension(session, info, oid, trans)


@router.delete("/dimension", summary=f"{PLACEHOLDER_PREFIX}delete_dimension")
@system_log(LogConfig(operation_type=OperationType.DELETE, module=OperationModules.METRIC, resource_id_expr='id_list'))
@require_permissions(permission=SqlbotPermission(role=['ws_admin']))
async def delete_dim(session: SessionDep, current_user: CurrentUser, id_list: list[int]):
    oid = current_user.oid
    delete_dimension(session, id_list, oid)
# ========= 【改造标记 METRIC-CENTER】↑ 指标中心 API 结束 =========
