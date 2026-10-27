"""# ========= 【改造标记 DSL-COMPILE】↓ Phase 5 SQL Builder 模块（DSL → SQL 确定性编译，G1 独立模块） =========

权威规格：v201改造方案_v1.2.md Phase 5 章节与第九节；方案分析 selfdoc/v201/detail/phase5-sql-builder方案分析.md。

分流原则（双轨永久，G2）：仅「单表聚合主干 + calculation=none + atomic 指标」进编译轨；
任一条件不满足/解析失败/编译异常 → 返回 None 走原 generate_sql（LLM 永久轨）。
开关关（DSL_COMPILE_ENABLED=False）= 零开销早退、不记 op17；开关开 = 必记一条 op17（含 no_plan）。
编译器自身故障绝不影响问数主流程：整包 try/except 兜底 → llm_fallback(internal_error)。

拍板（2026-10-26 五点全按建议）：
① 首期编译范围 aggregate/detail/trend + calculation=none + 单表 + atomic；
② 方言白名单首期 mysql/postgresql；
③ chart-type 规则映射 detail→table、trend→line、aggregate 有维度→bar/单值→table；
④ enforce 代码完整实现、走查临时开实测；
⑤ aggregation 仲裁以 metric_definition 固化口径为准 + op17 记差异（G3）。
"""
from typing import Any

import orjson
import sqlglot
from sqlalchemy import select as sa_select
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session
from sqlglot import exp

from apps.chat.curd.chat import end_log, start_log
from apps.chat.models.chat_model import OperationEnum
from apps.chat.schemas.query_plan import QueryPlan
from apps.db.db import get_sqlglot_dialect
from apps.metric.models.metric_model import (
    Dimension,
    MetricDefinition,
    MetricDimensionRelation,
)
from common.core.config import settings
from common.utils.utils import SQLBotLogUtil

# 拍板①：首期可编译 query_type；calculation 必须 none（compare/rank/share/yoy/qoq 属 Phase 6 或无结构字段）
COMPILED_QUERY_TYPES = {'aggregate', 'detail', 'trend'}
# 拍板②：首期方言白名单（按 ds.type 原值，doris/starrocks 等即使 sqlglot 族内也回退）
DIALECT_WHITELIST = {'mysql', 'postgresql'}
MONTH_ALIAS = '月份'
ROW_LIMIT = 1000  # 与提示词行限规则同源（enable_sql_row_limit 开时附加）
AGG_FUNCTIONS = {'sum': exp.Sum, 'count': exp.Count, 'avg': exp.Avg, 'max': exp.Max, 'min': exp.Min}

# operator 归一白名单（提示词枚举 =|!=|>|<|>=|<=|in|like + between），含中文/符号别名
_OPERATOR_ALIASES = {
    '=': 'eq', '==': 'eq', 'eq': 'eq', 'equals': 'eq', '等于': 'eq',
    '!=': 'ne', '<>': 'ne', 'ne': 'ne', 'neq': 'ne', '不等于': 'ne',
    '>': 'gt', 'gt': 'gt', '大于': 'gt',
    '<': 'lt', 'lt': 'lt', '小于': 'lt',
    '>=': 'ge', 'ge': 'ge', 'gte': 'ge', '大于等于': 'ge', '不小于': 'ge',
    '<=': 'le', 'le': 'le', 'lte': 'le', '小于等于': 'le', '不大于': 'le',
    'in': 'in',
    'not in': 'not_in',
    'like': 'like', 'contains': 'like', '包含': 'like',
    'between': 'between',
}
# trend 的 plan.dimensions 允许的时间词（其余非时间维度 → scope 回退）
_TIME_DIM_WORDS = {'月份', '月度', '年月', '统计日期', '日期', '时间', '年', '季度',
                   'date', 'month', 'year', 'time'}


class _Fallback(Exception):
    """编译轨内部回退信号：带 reason 码，由入口统一记 op17 后返回 None。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _metric_matches(name: str, ds_id: Any, metrics: list) -> Any | None:
    """按 metric_name（ci）解析；多 ds 命中优先当前 ds；空名/无命中 → None。"""
    target = (name or '').strip().lower()
    if not target:
        return None
    hits = [m for m in metrics if (m.metric_name or '').strip().lower() == target]
    for m in hits:
        if m.source_ds_id == ds_id:
            return m
    return hits[0] if hits else None


def _metric_in_ds(metric: Any, ds_id: Any) -> bool:
    if metric.source_ds_id is not None and metric.source_ds_id != ds_id:
        return False
    if metric.specific_ds and ds_id not in (metric.datasource_ids or []):
        return False
    return True


def _resolve_dims(session: Session, ds_id: Any) -> dict[str, Any]:
    """维度名与别名（ci）→ Dimension 行索引。"""
    rows = session.execute(sa_select(Dimension)).scalars().all()
    index: dict[str, Any] = {}
    for d in rows:
        if d.source_ds_id is not None and d.source_ds_id != ds_id:
            continue
        if d.dimension_name:
            index.setdefault(d.dimension_name.strip().lower(), d)
        for alias in (d.aliases or []):
            if isinstance(alias, str) and alias.strip():
                index.setdefault(alias.strip().lower(), d)
    return index


def _resolve_filter_column(field: str, table: str, session: Session,
                           dim_index: dict[str, Any]) -> str | None:
    """filter field → 列名：① 维度名/别名（同表）② 该表真实列名（core_field）。失败 → None。"""
    f = (field or '').strip()
    if not f:
        return None
    dim = dim_index.get(f.lower())
    if dim is not None:
        col = dim.column_name
        if not col:
            return None
        if dim.source_table and dim.source_table != table:
            return None
        return col
    # 真实列直配（术语库为纯文本词无结构映射，首期不作解析源——方案边界注记）
    try:
        rows = session.execute(sa_text(
            'select f.field_name from core_field f '
            'join core_table t on t.id = f.table_id '
            'where t.table_name = :tbl'), {'tbl': table}).fetchall()
        names = {(r[0] or '').strip().lower() for r in rows}
        if f.lower() in names:
            return f
    except Exception as e:  # noqa: BLE001
        SQLBotLogUtil.error(f'[DSL-COMPILE] core_field lookup failed: {e}', exc_info=True)
    return None


def _normalize_operator(op: str) -> str | None:
    return _OPERATOR_ALIASES.get((op or '').strip().lower())


def _lit(v: Any) -> exp.Literal:
    # 字面量统一按字符串常量输出（未知类型 literal 由目标库按列类型隐式强转，MySQL/PG 通用）
    if isinstance(v, bool):
        v = 'true' if v else 'false'
    return exp.Literal.string(str(v))


def _filter_condition(item: Any, column: str) -> exp.Condition | None:
    """单个 FilterItem → sqlglot 条件；值/operator 不合法 → None（调用方回退）。"""
    op = _normalize_operator(item.operator)
    if op is None:
        return None
    col = exp.column(column)
    if op == 'in':
        values = item.value if isinstance(item.value, (list, tuple)) else [item.value]
        if not values or any(v is None for v in values):
            return None
        return exp.In(this=col, expressions=[_lit(v) for v in values])
    if op == 'not_in':
        values = item.value if isinstance(item.value, (list, tuple)) else [item.value]
        if not values or any(v is None for v in values):
            return None
        return exp.Not(this=exp.In(this=col, expressions=[_lit(v) for v in values]))
    if op == 'between':
        values = item.value if isinstance(item.value, (list, tuple)) else []
        if len(values) != 2 or any(v is None for v in values):
            return None
        return exp.Between(this=col, low=_lit(values[0]), high=_lit(values[1]))
    if op == 'like':
        if item.value is None:
            return None
        v = str(item.value)
        if '%' not in v:
            v = f'%{v}%'
        return exp.Like(this=col, expression=exp.Literal.string(v))
    # 标量比较族
    if item.value is None or isinstance(item.value, (list, tuple)):
        return None
    rhs = _lit(item.value)
    return {'eq': exp.EQ, 'ne': exp.NEQ, 'gt': exp.GT, 'lt': exp.LT,
            'ge': exp.GTE, 'le': exp.LTE}[op](this=col, expression=rhs)


def _month_expr(column: str, read_dialect: str | None) -> exp.Expression:
    """月份提取表达式：MySQL 直接 SUBSTRING；PG 走 CAST(col AS text)（拍板②方言内通用）。"""
    if read_dialect == 'postgres':
        snippet = 'SUBSTRING(CAST(x AS text), 1, 7)'
    else:
        snippet = 'SUBSTRING(x, 1, 7)'
    node = sqlglot.parse_one(snippet, read=read_dialect)
    node.find(exp.Column).replace(exp.column(column))
    return node


def _chart_type(query_type: str, has_dims: bool) -> str:
    # 拍板③：规则映射（DSL 轨道无 LLM 选图表）
    if query_type == 'detail':
        return 'table'
    if query_type == 'trend':
        return 'line'
    return 'bar' if has_dims else 'table'


def _resolve_scope(plan: QueryPlan) -> str | None:
    """拍板① 范围判定（纯结构，不碰库）。返回 None=通过，否则 reason 码。"""
    if plan.query_type not in COMPILED_QUERY_TYPES:
        return 'scope'
    if plan.calculation.type != 'none':
        return 'scope'
    if plan.time_range is None:
        return 'no_time_range'
    if plan.time_range.previous is not None:
        return 'scope'
    if plan.query_type == 'detail' and not plan.dimensions:
        return 'scope'
    if plan.query_type == 'trend':
        for dim in plan.dimensions:
            if dim.strip().lower() not in _TIME_DIM_WORDS:
                return 'scope'
    if any(f.logic and f.logic != 'and' for f in plan.filters):
        return 'scope'
    return None


def _relation_enabled(session: Session, metric_id: Any, dimension_id: Any) -> bool:
    row = session.execute(sa_select(MetricDimensionRelation).where(
        MetricDimensionRelation.metric_id == metric_id,
        MetricDimensionRelation.dimension_id == dimension_id,
        MetricDimensionRelation.enabled == True,  # noqa: E712
    )).scalars().first()
    return row is not None


def _compile(plan: QueryPlan, service, session: Session, metrics: list,
             dim_index: dict[str, Any]) -> tuple[str, dict]:
    """解析 + sqlglot AST 组装（禁字符串拼接）。返回 (sql, meta)；不满足 → raise _Fallback(reason)。"""
    # ---- 指标解析（G3 仲裁：固化口径优先，plan aggregation 差异记 meta 不回退） ----
    agg_mismatch: list[dict] = []
    resolved: list[dict] = []
    for ref in plan.metrics:
        m = _metric_matches(ref.metric_name, service.ds.id, metrics)
        if m is None or not _metric_in_ds(m, service.ds.id):
            raise _Fallback('metric_resolve')
        if (m.metric_type or 'atomic') != 'atomic':
            raise _Fallback('not_atomic')
        if not m.source_table or not m.source_column or not m.aggregation:
            raise _Fallback('metric_resolve')
        agg_key = (m.aggregation or '').strip().lower()
        if agg_key not in AGG_FUNCTIONS:
            raise _Fallback('metric_resolve')
        if ref.aggregation and ref.aggregation.strip().lower() != agg_key:
            agg_mismatch.append({'metric': m.metric_name,
                                 'plan': ref.aggregation, 'resolved': m.aggregation})
        resolved.append({'row': m, 'agg': agg_key})
    tables = {r['row'].source_table for r in resolved}
    if len(tables) != 1:
        raise _Fallback('multi_table')
    table = next(iter(tables))
    metric0 = resolved[0]['row']
    ds_type = (service.ds.type or '').lower()
    read_dialect = get_sqlglot_dialect(ds_type)

    # ---- 维度解析（trend 特例：时间词维度按 time_field 月分组） ----
    dim_cols: list[str] = []
    if plan.query_type != 'trend':
        for name in plan.dimensions:
            dim = dim_index.get(name.strip().lower())
            if dim is None or not dim.column_name:
                raise _Fallback('dimension_resolve')
            if dim.source_table and dim.source_table != table:
                raise _Fallback('dimension_resolve')
            for r in resolved:
                if not _relation_enabled(session, r['row'].id, dim.id):
                    raise _Fallback('relation')
            dim_cols.append(dim.column_name)

    # ---- 时间与过滤条件 ----
    if not metric0.time_field:
        raise _Fallback('no_time_field')
    conditions: list[exp.Condition] = [
        exp.GTE(this=exp.column(metric0.time_field),
                expression=_lit(plan.time_range.current.start)),
        exp.LTE(this=exp.column(metric0.time_field),
                expression=_lit(plan.time_range.current.end)),
    ]
    for item in plan.filters:
        column = _resolve_filter_column(item.field, table, session, dim_index)
        if column is None:
            raise _Fallback('filter_resolve')
        cond = _filter_condition(item, column)
        if cond is None:
            raise _Fallback('operator')
        conditions.append(cond)

    # ---- AST 组装（sqlglot>=20 builder 不可变：每步必须重赋值） ----
    select = exp.Select()
    if plan.query_type == 'trend':
        select = select.select(exp.alias_(_month_expr(metric0.time_field, read_dialect), MONTH_ALIAS))
    for r in resolved:
        agg_cls = AGG_FUNCTIONS[r['agg']]
        expr = agg_cls(this=exp.column(r['row'].source_column))
        select = select.select(exp.alias_(expr, r['row'].metric_name))
    for c in dim_cols:
        select = select.select(exp.column(c))
    select = select.from_(exp.table_(table))
    select = select.where(*conditions)
    if plan.query_type == 'trend':
        select = select.group_by(exp.column(MONTH_ALIAS)).order_by(exp.column(MONTH_ALIAS))
    elif plan.query_type == 'aggregate' and dim_cols:
        # detail 是裸列明细，不聚合不分组
        select = select.group_by(*[exp.column(c) for c in dim_cols])
    if getattr(service, 'enable_sql_row_limit', False):
        select = select.limit(ROW_LIMIT)

    sql_out = select.sql(dialect=read_dialect)

    # ---- 自检：可解析 ∧ 表白名单（失败 → 回退而非抛错；避免 import llm 的循环依赖） ----
    try:
        parsed = sqlglot.parse_one(sql_out, read=read_dialect)
        used = {t.name for t in parsed.find_all(exp.Table)}
    except Exception as e:  # noqa: BLE001
        raise _Fallback('self_check') from e
    allowed = {str(a).split('.')[-1].strip('`"') for a in (service.table_name_list or [])}
    if not used or not used.issubset(allowed):
        raise _Fallback('self_check')

    meta = {'table': table, 'metric': '、'.join(r['row'].metric_name for r in resolved),
            'dimensions': dim_cols, 'agg_mismatch': agg_mismatch,
            'chart_type': _chart_type(plan.query_type, bool(dim_cols) or plan.query_type == 'trend'),
            'query_type': plan.query_type}
    return sql_out, meta


def compile_plan_to_answer(service, _session: Session,
                           plan: QueryPlan | None) -> str | None:
    """Plan 分流入口：编译成功返回合成 answer（str），否则 None（走 generate_sql）。

    service: llm service 实例（读 ds/table_name_list/enable_sql_row_limit/record）；
    调用方 llm.py 仅一行调用（G1）。副作用：service._dsl_compiled / service._dsl_meta。
    """
    if not settings.DSL_COMPILE_ENABLED:
        return None

    service._dsl_compiled = False
    meta: dict[str, Any] = {'route': 'llm_fallback', 'reason': 'internal_error'}
    log = start_log(session=_session, operate=OperationEnum.DSL_COMPILE,
                    record_id=service.record.id, local_operation=True)
    try:
        reason = _resolve_scope(plan) if plan is not None else 'no_plan'
        if reason is None:
            ds_type = (service.ds.type or '').lower()
            if ds_type not in DIALECT_WHITELIST:
                reason = 'dialect'
        if reason is None:
            metrics = list(_session.execute(sa_select(MetricDefinition)).scalars().all())
            dim_index = _resolve_dims(_session, service.ds.id)
            sql_out, compiled_meta = _compile(plan, service, _session, metrics, dim_index)
            answer = orjson.dumps({
                'success': True,
                'sql': sql_out,
                'tables': [compiled_meta['table']],
                'chart-type': compiled_meta['chart_type'],
            }).decode()
            meta = {'route': 'dsl', 'reason': '', 'sql': sql_out, **compiled_meta}
            service._dsl_compiled = True
            service._dsl_meta = meta
            return answer
        meta = {'route': 'llm_fallback', 'reason': reason}
    except Exception as e:  # noqa: BLE001
        # 编译器自身故障绝不影响问数主流程（G2）：_Fallback 与意外异常统一回退
        reason = getattr(e, 'reason', None)
        meta = {'route': 'llm_fallback', 'reason': reason or 'internal_error'}
        if reason is None:
            SQLBotLogUtil.error(f'[DSL-COMPILE] internal error: {e}', exc_info=True)
    finally:
        service._dsl_meta = meta
        end_log(session=_session, log=log,
                full_message=[{'type': 'ai',
                               'content': orjson.dumps(meta, default=str).decode()}])
    return None


# ========= 【改造标记 DSL-COMPILE】↑ Phase 5 SQL Builder 模块结束 =========
