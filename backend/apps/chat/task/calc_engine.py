"""# ========= 【改造标记 CALC-ENGINE】↓ Phase 6 计算引擎（Post-Query Calculation Engine，G1 独立模块） =========

权威规格：v201改造方案_v1.2.md Phase 6 章节（第四节 L217-228、第九节步骤 18）；
方案分析 selfdoc/v201/detail/phase6-calc-engine方案分析.md（2026-10-28 拍板 ①~⑤ 全按建议）。

形态（拍板①，经问题17 方案C 修正 2026-10-29）：主 SQL 优先由「编译轨」供给当期窗数据
（calculation∈CALC_COMPILE_TYPES 的计算题经 sql_builder 编译成当期 SQL，LLM 不生成主 SQL），
本模块只做「补前期窗子查询 + Python 公式合并」；插桩在 llm.py 3-B 之后、DataFormat/save 之前。
LLM 轨（编译范围外回退直答）主 data 无指标列 → contract_mismatch 跳过不接管（防破坏答案型 SQL）。
范围（拍板②）：calculation ∈ {yoy, qoq, growth} × query_type ∈ {aggregate, compare}
+ 单指标 + 单表 atomic（复用 Phase 5 _compile，仅换时间窗）；share/rank/detail/trend 回退。
回退不计算（拍板③，G2 四场景）：contract_mismatch（LLM 答案型 SQL，2026-10-29 增）/
row_permission（行权限/dynamic 改写）/ no_previous / 组装失败
——一律记 op19 卡 reason、当期数据照常返回、绝不阻断。
合并行结构（拍板④+列结构 A）：{维度…, <指标名>=当期值, 同期值, 变化值, 变化率}；
按维度 key full-join（当期先行序）；变化率=(当期-基期)/基期，基期 0 → None（div_zero）。
日志卡（拍板⑤）：OperationEnum.CALC_ENGINE='19'，calculation≠none 每题必记（含回退 reason）；
calculation=none 的普通题不记卡（零打扰）。开关 CALC_ENGINE_ENABLED=False（拍板⑥）。
"""
from typing import Any

import orjson
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from apps.chat.curd.chat import end_log, start_log
from apps.chat.models.chat_model import OperationEnum
from apps.chat.schemas.query_plan import QueryPlan
from apps.chat.task.sql_builder import (
    CALC_COMPILE_TYPES,
    DIALECT_WHITELIST,
    _compile,
    _Fallback,
    _resolve_dims,
)
from apps.metric.models.metric_model import MetricDefinition
from common.core.config import settings
from common.utils.utils import SQLBotLogUtil

# 拍板②：本期支持的 calculation 与 query_type（其余/结构不满足 → 回退 reason）
# 问题17 方案C：与 sql_builder.CALC_COMPILE_TYPES 单一同源（反向 import 成环，常量定义于 sql_builder）
SUPPORTED_CALC_TYPES = CALC_COMPILE_TYPES
SUPPORTED_QUERY_TYPES = {'aggregate', 'compare'}
# 合并输出列（拍板④：变化率=小数；任一期缺失/null → 该行对应列 None）
COL_PREV = '同期值'
COL_CHANGE = '变化值'
COL_RATE = '变化率'
_VALUES_LOG_CAP = 50  # 日志 values 明细截断上限（防爆量；超限记 truncated）


def _cell(row: dict, col: str) -> Any:
    """按列名取值：兼容 exec_sql 的 qualified key（`表.列` / 反引号）。"""
    if col in row:
        return row[col]
    for k, v in row.items():
        if str(k).split('.')[-1].strip('`"') == col:
            return v
    return None


def _num(v: Any) -> float | None:
    """数值化（公式入参）：失败/None → None（null 确定性传播，不抛错）。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _change(cur: float | None, base: float | None) -> tuple[float | None, float | None, str | None]:
    """公式（yoy/qoq/growth 同构）：变化值=当期-基期；变化率=(当期-基期)/基期。
    返回 (change, rate, note)；任一期 None → 全 None；基期=0 → rate=None 且 note=div_zero。"""
    if cur is None or base is None:
        return None, None, None
    delta = cur - base
    if base == 0:
        return delta, None, 'div_zero'
    return delta, delta / base, None


def _merge(cur_rows: list[dict], prev_rows: list[dict], meta: dict) -> tuple[list[dict], list[dict]]:
    """两期 full-join 合并（拍板④列结构 A）：{维度…, <指标名>=当期值, 同期值, 变化值, 变化率}。

    当期 key 先行（保主序），前期独有 key 追加；无维度=单 key。返回 (merged, values 明细)。
    """
    dim_cols: list[str] = meta.get('dimensions') or []
    metric_name: str = meta.get('metric') or ''
    # dim_cols 是 SQL 列名；输出维度列头用列名（与既有数据行 key 形态一致，normalize 不再改）
    cur_by_key = {tuple(_cell(r, c) for c in dim_cols): r for r in cur_rows}
    prev_by_key = {tuple(_cell(r, c) for c in dim_cols): r for r in prev_rows}

    keys: list[tuple] = []
    seen: set[tuple] = set()
    for r in cur_rows + prev_rows:
        k = tuple(_cell(r, c) for c in dim_cols)
        if k not in seen:
            seen.add(k)
            keys.append(k)

    merged: list[dict] = []
    values: list[dict] = []
    for k in keys:
        cur_row = cur_by_key.get(k)
        prev_row = prev_by_key.get(k)
        cur_v = _num(_cell(cur_row, metric_name)) if cur_row is not None else None
        prev_v = _num(_cell(prev_row, metric_name)) if prev_row is not None else None
        delta, rate, note = _change(cur_v, prev_v)
        out: dict[str, Any] = dict(zip(dim_cols, k, strict=False))
        out[metric_name] = cur_v
        out[COL_PREV] = prev_v
        out[COL_CHANGE] = delta
        out[COL_RATE] = rate
        merged.append(out)
        if len(values) < _VALUES_LOG_CAP:
            entry = {'dims': dict(zip(dim_cols, k, strict=False)), 'current': cur_v, 'previous': prev_v,
                     'change': delta, 'rate': rate}
            if note:
                entry['note'] = note
            values.append(entry)
    return merged, values


def build_rule_chart(rows: list[dict], dimensions: list[str], metric: str, title: str) -> dict:
    """方案D（问题18 拍板 2026-10-30）：计算引擎接管成功 → 确定性 table 图表配置（跳过 LLM 图表生成）。

    列 = 合并数据首行 keys（= 维度… + <指标名>/同期值/变化值/变化率，顺序与拍板④一致）；
    数据为空时以 dimensions+metric 兜底同列集。问题 17/18 根因：LLM 图表环节按
    「当期单值 SQL」生成列引用，合并数据 4 列白给——方案 D 以规则配置精确指列。
    """
    if rows:
        cols = [str(c) for c in rows[0].keys()]
    else:
        cols = [str(c) for c in list(dimensions) + [metric, COL_PREV, COL_CHANGE, COL_RATE] if c]
    return {'type': 'table', 'title': title or '',
            'columns': [{'name': c, 'value': c} for c in cols]}


def compute(service, _session: Session, result: dict) -> bool:
    """主插桩入口（llm.py 3-B 后单点调用，整包兜底绝不影响主流程 G2）。

    计算成功 → 就地替换 result['data'] 并返回 True；任何回退 → 数据不动返回 False。
    卡记账规则：开关关 / 无 plan / calculation=none → 不记卡（零打扰）；
    calculation≠none（含 share/rank 回退）→ 必记一条 op19（拍板⑤）。
    方案D（2026-10-30）：成功置 service._calc_computed=True（llm.py 图表段规则接管依据）；
    函数首行统一置 False，防服务实例复用残留。
    """
    service._calc_computed = False  # 方案D：每题重置（开关关/早退路径同样干净）
    if not settings.CALC_ENGINE_ENABLED:
        return False
    plan: QueryPlan | None = getattr(service, 'query_plan', None)
    if plan is None or plan.calculation.type == 'none':
        return False

    calc_type = plan.calculation.type
    meta: dict[str, Any] = {'type': calc_type, 'query_type': plan.query_type,
                            'computed': False, 'reason': '',
                            'compiled_takeover': bool(getattr(service, '_dsl_compiled', False))}
    if plan.time_range is not None:
        meta['window_current'] = vars(plan.time_range.current) if plan.time_range.current else None
        if plan.time_range.previous is not None:
            meta['window_previous'] = vars(plan.time_range.previous)
    log = start_log(session=_session, operate=OperationEnum.CALC_ENGINE,
                    record_id=service.record.id, local_operation=True)
    try:
        reason = _resolve_skip(service, plan, result)
        if reason is None:
            reason = _execute_and_merge(service, _session, plan, result, meta)
        meta['reason'] = reason or ''
        if not reason:
            meta['computed'] = True
            service._calc_computed = True  # 方案D：llm.py 图表段规则接管触发
            return True
    except _Fallback as e:
        meta['reason'] = e.reason
    except Exception as e:  # noqa: BLE001
        meta['reason'] = 'internal_error'
        SQLBotLogUtil.error(f'[CALC-ENGINE] internal error: {e}', exc_info=True)
    finally:
        end_log(session=_session, log=log,
                full_message=[{'type': 'ai',
                               'content': orjson.dumps(meta, default=str).decode()}])
    return False


def _has_metric_col(rows: list[dict], metric_name: str) -> bool:
    """当期数据契约检测（问题17 方案C 兜底）：首行 key 是否含指标列（兼容 qualified key）。"""
    if not rows:
        return True  # 空结果无破坏风险，放行走既有合并语义（前期独有行当期 null）
    return _cell(rows[0], metric_name) is not None


def _resolve_skip(service, plan: QueryPlan, result: dict) -> str | None:
    """拍板③ 回退判定（纯结构 + guard，不碰库）。返回 None=可计算，否则 reason 码。

    问题17 方案C（2026-10-29）：当期数据契约判定前置——
    编译接管（_dsl_compiled）下主 SQL 为当期窗数据（列=指标名），正常接管；
    LLM 轨（未编译接管，如编译范围外回退直答）主 SQL 可能是「答案型 SQL」，
    若主 data 不含指标列 → 引擎不接管（防整体替换破坏 LLM 已算好的结果）。
    """
    if not getattr(service, '_dsl_compiled', False):
        if not _has_metric_col(list(result.get('data') or []), plan.metrics[0].metric_name):
            return 'contract_mismatch'
    if getattr(service, '_row_guard', False):
        # 行权限/dynamic 改写生效：前期子查询若不完整施加权限存在泄露风险（首期回退）
        return 'row_permission'
    if plan.time_range is None or plan.time_range.previous is None:
        return 'no_previous'
    if plan.calculation.type not in SUPPORTED_CALC_TYPES:
        return 'unsupported_calc'
    if plan.query_type not in SUPPORTED_QUERY_TYPES:
        return 'scope'
    if len(plan.metrics) != 1:
        return 'multi_metric'
    ds_type = (service.ds.type or '').lower()
    if ds_type not in DIALECT_WHITELIST:
        return 'dialect'
    return None


def _execute_and_merge(service, _session: Session, plan: QueryPlan,
                       result: dict, meta: dict) -> str | None:
    """组装前期子查询 → 执行 → 公式合并 → 就地替换 result['data']。返回 None=成功，否则 reason。"""
    metrics = list(_session.execute(sa_select(MetricDefinition)).scalars().all())
    dim_index = _resolve_dims(_session, service.ds.id)
    prev_sql, prev_meta = _compile(plan, service, _session, metrics, dim_index,
                                   time_window=plan.time_range.previous)
    meta['sql_previous'] = prev_sql
    prev_data = (service.execute_sql(sql=prev_sql) or {}).get('data') or []
    cur_data = result.get('data') or []
    merged, values = _merge(list(cur_data), list(prev_data), prev_meta)
    meta['row_count'] = len(merged)
    meta['values'] = values
    if len(values) >= _VALUES_LOG_CAP and (len(cur_data) + len(prev_data)) > _VALUES_LOG_CAP * 2:
        meta['values_truncated'] = True
    result['data'] = merged
    return None


# ========= 【改造标记 CALC-ENGINE】↑ Phase 6 计算引擎模块结束 =========
