# ========= 【改造标记 TRUST-VALIDATE】↓ Phase 3-A 指标口径校验器（G1：实现落独立模块，llm.py 仅薄插桩） =========
"""3-A 口径校验（告警级 log-only，G4 先观测后阻断）。

在 SQL 生成后、执行前做两类静态检查，违规仅记告警日志（LLM 轨道始终告警，G2 不误伤）：

1. 列存在性硬底线（讨论结论 3.4-5，零配置可判定）：
   SQL 引用的列必须存在于对应勾选表的 core_field 中。排除 CTE 引用、子查询/派生表别名、
   SELECT 计算别名（防误报）；未限定列名比对全部命中表字段的并集。
   类型校验（如 varchar 与数值直比）本期不做——误报率高，留待规则细化后补。
2. 指标规则（metric_rule 表，按指标召回命中做"问题↔指标"弱绑定）——仅当命中指标的
   source_table ∈ SQL 表 或 source_column ∈ SQL 列时加载该指标规则：
   - required_filter：rule_content 为逗号/顿号/空格分隔的字段列表，必须出现在 SQL 的 WHERE/HAVING 中；
   - forbidden_field：同上分隔，这些字段禁止出现在 SQL 中；
   - forced_agg：单个聚合函数名（sum/count/avg/max/min）；命中指标 source_column 已被聚合
     但函数不符才告警，未聚合则跳过（保守策略，避免误伤）。

任何内部异常只记日志、返回已收集结果，绝不阻断问数主流程（G2）。
"""
import json
from typing import Any, Optional

import sqlglot
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlglot import exp

from common.utils.utils import SQLBotLogUtil

_LOG_PREFIX = '[TRUST-VALIDATE][METRIC-RULE]'


def _log_violation(payload: dict) -> None:
    SQLBotLogUtil.warning(_LOG_PREFIX + ' ' + json.dumps(payload, ensure_ascii=False, default=str))


def _split_fields(rule_content: str) -> list[str]:
    normalized = rule_content or ''
    for sep in (',', '，', '、', ' '):
        normalized = normalized.replace(sep, ',')
    return [f.strip().strip('`[]"\'').lower() for f in normalized.split(',') if f.strip()]


def _parse_sql(sql: str, ds_type: Optional[str]) -> tuple[Optional[exp.Expression], dict[str, str]]:
    """解析 SQL → (首条语句, 表引用映射{裸名或别名: 真实表名})；解析失败返回 (None, {})。"""
    try:
        try:
            from apps.db.db import get_sqlglot_dialect
        except ImportError:
            # 既有环境问题：xpack↔assistant 循环导入使 apps.db.db 无法在全新进程里首先导入。
            # 先引导 sqlbot_xpack 破环后重试；应用正常启动路径中 apps.db.db 已加载，走不到这里。
            import sqlbot_xpack  # noqa: F401
            from apps.db.db import get_sqlglot_dialect
        dialect = get_sqlglot_dialect(ds_type)
        statements = [s for s in sqlglot.parse(sql, dialect=dialect) if s is not None]
    except Exception as e:  # noqa: BLE001
        SQLBotLogUtil.error(f'[TRUST-VALIDATE] parse SQL failed: {e}', exc_info=True)
        return None, {}
    if not statements:
        return None, {}
    stmt = statements[0]
    cte_names = {cte.alias.lower() for cte in stmt.find_all(exp.CTE) if cte.alias}
    alias_map: dict[str, str] = {}
    for table in stmt.find_all(exp.Table):
        name = (table.name or '').lower()
        if not name or name in cte_names:
            continue
        alias_map[name] = name
        if table.alias:
            alias_map[table.alias.lower()] = name
    return stmt, alias_map


def _column_refs(node: Any) -> list[tuple[str, str]]:
    """节点内全部 (限定符, 列名)，小写；限定符可能为空串。"""
    return [((col.table or '').lower(), (col.name or '').lower())
            for col in node.find_all(exp.Column)]


def _load_known_fields(session: Session, ds_id: Any, table_names: list[str]) -> dict[str, set[str]]:
    """已勾选表的字段清单：{小写表名: {小写字段名}}；ds_id 或表清单为空返回空。"""
    if not ds_id or not table_names:
        return {}
    rows = session.execute(text("""
        SELECT LOWER(t.table_name) AS tbl, LOWER(f.field_name) AS fld
        FROM core_table t
        JOIN core_field f ON f.table_id = t.id
        WHERE t.ds_id = :ds_id AND t.table_name = ANY(:tables)
          AND COALESCE(f.checked, TRUE)
    """), {'ds_id': ds_id, 'tables': table_names}).all()
    known: dict[str, set[str]] = {}
    for row in rows:
        known.setdefault(row.tbl, set()).add(row.fld)
    return known


def _check_columns(stmt: exp.Expression, alias_map: dict[str, str],
                   known: dict[str, set[str]]) -> list[dict]:
    violations: list[dict] = []
    select_aliases = {(a.alias or '').lower() for a in stmt.find_all(exp.Alias) if a.alias}
    union_fields: set[str] = set()
    for fields in known.values():
        union_fields |= fields
    for qualifier, col in _column_refs(stmt):
        if not col or col == '*' or col in select_aliases:
            continue
        if qualifier:
            real = alias_map.get(qualifier)
            if real and real in known and col not in known[real]:
                violations.append({'kind': 'column_missing', 'table': real, 'column': col,
                                   'detail': 'SQL 引用了表中不存在（或未勾选）的字段'})
        elif union_fields and col not in union_fields:
            violations.append({'kind': 'column_missing', 'table': '', 'column': col,
                               'detail': '未限定列名不属于命中表的任何勾选字段'})
    return violations


def _load_rules(session: Session, metric_names: list[str]) -> list[dict[str, str]]:
    """按指标名加载启用中的规则（候选项 dict 无 metric id，按 name 关联）。"""
    if not metric_names:
        return []
    rows = session.execute(text("""
        SELECT LOWER(md.metric_name) AS metric_name,
               LOWER(COALESCE(r.rule_type, '')) AS rule_type,
               COALESCE(r.rule_content, '') AS rule_content,
               LOWER(COALESCE(md.source_table, '')) AS source_table,
               LOWER(COALESCE(md.source_column, '')) AS source_column
        FROM metric_rule r
        JOIN metric_definition md ON md.id = r.metric_id
        WHERE LOWER(md.metric_name) = ANY(:names) AND COALESCE(r.status, TRUE)
    """), {'names': metric_names}).all()
    return [dict(row._mapping) for row in rows]


def _metric_touches_sql(rule: dict, real_tables: set[str], all_col_names: set[str]) -> bool:
    source_table = rule.get('source_table') or ''
    source_column = rule.get('source_column') or ''
    return (bool(source_table) and source_table in real_tables) or \
           (bool(source_column) and source_column in all_col_names)


def _apply_rule(rule: dict, stmt: exp.Expression, all_col_names: set[str]) -> Optional[dict]:
    rule_type = rule.get('rule_type') or ''
    content = rule.get('rule_content') or ''
    payload: dict[str, Any] = {'kind': 'metric_rule', 'metric_name': rule.get('metric_name'),
                               'rule_type': rule_type, 'rule_content': content}

    if rule_type == 'required_filter':
        where_cols: set[str] = set()
        for node in (stmt.find(exp.Where), stmt.find(exp.Having)):
            if node is not None:
                where_cols.update(name for _, name in _column_refs(node))
        missing = [f for f in _split_fields(content) if f not in where_cols]
        if missing:
            payload['detail'] = f'要求出现在 WHERE/HAVING 的字段缺失: {missing}'
            return payload
        return None

    if rule_type == 'forbidden_field':
        hit = [f for f in _split_fields(content) if f in all_col_names]
        if hit:
            payload['detail'] = f'禁止引用的字段出现在 SQL 中: {hit}'
            return payload
        return None

    if rule_type == 'forced_agg':
        forced = content.strip().lower()
        source_column = rule.get('source_column') or ''
        if not forced or not source_column:
            return None
        agg_types = {type(fn).__name__.lower()
                     for fn in stmt.find_all(exp.AggFunc)
                     for _, name in _column_refs(fn)
                     if name == source_column}
        if agg_types and forced not in agg_types:
            payload['detail'] = f'指标字段 {source_column} 使用聚合 {sorted(agg_types)}，规则要求 {forced}'
            return payload
        return None
    return None


def check_metric_rule_violations(session: Session, sql: str,
                                  metric_candidates: Optional[list] = None,
                                  ds_id: Any = None, ds_type: Optional[str] = None,
                                  record_id: Any = None) -> list[dict]:
    """口径校验入口：返回违规清单并逐条写告警日志；任何故障不影响调用方主流程。

    metric_candidates 为空（Phase 1 关/召回空）= 不校验，零成本直接返回（规格：无命中不校验）。
    """
    violations: list[dict] = []
    if not sql or not metric_candidates:
        return violations
    try:
        stmt, alias_map = _parse_sql(sql, ds_type)
        if stmt is None:
            return violations
        real_tables = set(alias_map.values())
        all_col_names = {name for _, name in _column_refs(stmt)}

        # 1) 列存在性硬底线
        try:
            known = _load_known_fields(session, ds_id, sorted(real_tables))
        except Exception as e:  # noqa: BLE001
            SQLBotLogUtil.error(f'[TRUST-VALIDATE] load core fields failed: {e}', exc_info=True)
            known = {}
        if known:
            for v in _check_columns(stmt, alias_map, known):
                v['record_id'] = record_id
                violations.append(v)
                _log_violation(v)

        # 2) 指标规则（弱绑定：命中指标且 SQL 触及其表/字段才加载）
        metric_names = sorted({(m.get('metric_name') or '').strip().lower()
                               for m in metric_candidates
                               if isinstance(m, dict) and m.get('metric_name')})
        for rule in _load_rules(session, metric_names):
            if not _metric_touches_sql(rule, real_tables, all_col_names):
                continue
            v = _apply_rule(rule, stmt, all_col_names)
            if v:
                v['record_id'] = record_id
                violations.append(v)
                _log_violation(v)
    except Exception as e:  # noqa: BLE001
        # 校验器自身故障绝不影响问数主流程（G2）
        SQLBotLogUtil.error(f'[TRUST-VALIDATE] metric rule check failed: {e}', exc_info=True)
    return violations
# ========= 【改造标记 TRUST-VALIDATE】↑ Phase 3-A 校验器结束 =========
