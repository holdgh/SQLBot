# ========= 【改造标记 TRUST-VALIDATE】↓ Phase 3-B 结果校验器（G1：实现落独立模块，llm.py 仅薄插桩） =========
"""3-B Result Validator（log-only，前端零变化；设计供 DSL/LLM 两轨共用）。

开关 RESULT_VALIDATOR_ENABLED 开启后生效，检查后仍仅记告警日志不阻断（strict 后置未实现）。

L1 通用检查（与指标无关）：
- 空结果 / 行数超限（RESULT_VALIDATOR_MAX_ROWS，可配）/ 全 NULL 列 / 数值量级超限（RESULT_VALIDATOR_MAX_VALUE，可配）；
- 主键重复本期跳过：core_field 无主键元数据，无法可靠判定（进展文档已标注该边界）。
L2 指标级检查：命中指标的 normal_range{min,max} 对结果中同名列（source_column 或 metric_name 命中列名）
  做区间校验，越界告警疑似单位/量级错误——指标录入即自动生效（Phase 1 unit/normal_range 数据铺垫兑现）。

任何内部异常只记日志、返回已收集结果，绝不阻断问数主流程（G2）。
"""
import json
import math
from typing import Any, Iterator, Optional

from common.core.config import settings
from common.utils.utils import SQLBotLogUtil

_LOG_PREFIX = '[TRUST-VALIDATE][RESULT]'


def _log_violation(payload: dict) -> None:
    SQLBotLogUtil.warning(_LOG_PREFIX + ' ' + json.dumps(payload, ensure_ascii=False, default=str))


def _is_null(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == '')


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        return num if math.isfinite(num) else None
    if isinstance(value, str):
        try:
            num = float(value.strip())
        except ValueError:
            return None
        return num if math.isfinite(num) else None
    return None


def _iter_field_values(data: list, field: str) -> Iterator[Any]:
    for row in data:
        if isinstance(row, dict):
            yield row.get(field)


def validate_query_result(result: Optional[dict], metric_candidates: Optional[list] = None,
                           sql: str = '', record_id: Any = None) -> list[dict]:
    """结果校验入口：返回违规清单并逐条写告警日志；开关关/任何故障均不影响调用方主流程。"""
    violations: list[dict] = []
    if not settings.RESULT_VALIDATOR_ENABLED:
        return violations
    try:
        data = (result or {}).get('data') or []
        fields = [str(f).lower() for f in ((result or {}).get('fields') or [])]
        base: dict[str, Any] = {'record_id': record_id, 'sql_head': (sql or '')[:500]}

        # ---- L1 通用检查 ----
        if not data:
            v = {**base, 'kind': 'result_empty', 'detail': 'SQL 执行结果为空（疑似过滤条件过严或数据口径不符）'}
            violations.append(v)
            _log_violation(v)
        elif len(data) > settings.RESULT_VALIDATOR_MAX_ROWS:
            v = {**base, 'kind': 'result_rows_exceeded', 'row_count': len(data),
                 'detail': f'结果行数 {len(data)} 超过阈值 {settings.RESULT_VALIDATOR_MAX_ROWS}'}
            violations.append(v)
            _log_violation(v)

        dict_rows = bool(data) and all(isinstance(r, dict) for r in data)
        if dict_rows:
            null_cols = [field for field in fields
                         if all(_is_null(x) for x in _iter_field_values(data, field))]
            if null_cols:
                v = {**base, 'kind': 'result_all_null_column', 'columns': null_cols,
                     'detail': f'结果中存在全空列: {null_cols}'}
                violations.append(v)
                _log_violation(v)

            for field in fields:
                for value in _iter_field_values(data, field):
                    num = _to_number(value)
                    if num is not None and abs(num) > settings.RESULT_VALIDATOR_MAX_VALUE:
                        v = {**base, 'kind': 'result_magnitude', 'column': field, 'value': num,
                             'limit': settings.RESULT_VALIDATOR_MAX_VALUE,
                             'detail': f'列 {field} 数值 {num} 超过量级上限 {settings.RESULT_VALIDATOR_MAX_VALUE}（疑似单位/量级错误）'}
                        violations.append(v)
                        _log_violation(v)
                        break  # 每列最多告警一次

            # ---- L2 指标级检查（normal_range 区间） ----
            field_set = set(fields)
            for cand in metric_candidates or []:
                if not isinstance(cand, dict):
                    continue
                normal_range = cand.get('normal_range')
                if not isinstance(normal_range, dict):
                    continue
                try:
                    raw_min, raw_max = normal_range.get('min'), normal_range.get('max')
                    vmin = float(raw_min) if raw_min not in (None, '') else None
                    vmax = float(raw_max) if raw_max not in (None, '') else None
                except (TypeError, ValueError):
                    continue
                if vmin is None and vmax is None:
                    continue
                metric_name = cand.get('metric_name') or ''
                matched_cols = {str(c).lower() for c in (cand.get('source_column'), metric_name)
                                if c and str(c).lower() in field_set}
                for col in matched_cols:
                    for value in _iter_field_values(data, col):
                        num = _to_number(value)
                        if num is None:
                            continue
                        if (vmin is not None and num < vmin) or (vmax is not None and num > vmax):
                            v = {**base, 'kind': 'result_metric_range', 'metric_name': metric_name,
                                 'column': col, 'value': num, 'min': vmin, 'max': vmax,
                                 'unit': cand.get('unit') or '',
                                 'detail': f'指标 {metric_name} 结果值 {num} 超出正常区间 [{vmin}, {vmax}]（疑似单位/量级错误）'}
                            violations.append(v)
                            _log_violation(v)
                            break  # 每列最多告警一次
    except Exception as e:  # noqa: BLE001
        # 校验器自身故障绝不影响问数主流程（G2）
        SQLBotLogUtil.error(f'[TRUST-VALIDATE] result check failed: {e}', exc_info=True)
    return violations
# ========= 【改造标记 TRUST-VALIDATE】↑ Phase 3-B 校验器结束 =========
