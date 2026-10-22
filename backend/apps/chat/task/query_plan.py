"""# ========= 【改造标记 QUERY-PLAN】↓ Query Plan 生成模块（Phase 4 语义解析层，G1 独立模块） =========

权威规格：v201改造方案_v1.2.md Phase 4 章节；方案分析 selfdoc/v201/detail/phase4-query-plan方案分析.md。

纯旁路：开关关 = 返回 None 零行为；开关开 = LLM 解析 → strict 校验 → 混合置信度 → 步骤日志。
任何异常吞掉记日志返回 None，永不阻断问数主流程（plan 失败 → 调用方照走 generate_sql）。
"""
from datetime import date

import orjson
from langchain_core.messages import BaseMessageChunk
from pydantic import ValidationError

from apps.chat.curd.chat import end_log, start_log
from apps.chat.models.chat_model import (
    HumanPromptMessage,
    OperationEnum,
    SystemPromptMessage,
)
from apps.chat.schemas.query_plan import ConfidenceSignals, QueryPlan
from common.core.config import settings
from common.utils.utils import SQLBotLogUtil, extract_nested_json

QUERY_PLAN_SYSTEM_PROMPT = """你是查询理解器：把用户问题解析为 Query Plan。只输出一个 JSON 对象，禁止任何其他文字。

字段与规则：
- query_type: aggregate(聚合) | detail(明细) | trend(趋势) | rank(排名) | compare(对比)
- metrics: [{metric_name: 指标名(必填), aggregation: sum/count/avg/max/min(可选)}]，至少 1 个
- dimensions: 分组维度名数组（无则 []）
- filters: [{field: 字段名, operator: =|!=|>|<|>=|<=|in|like, value: 值, logic: and|or(可选)}]
- time_range: {current: {start, end}, previous: {start, end}}，ISO 日期；仅同比/环比/对比类才输出 previous；时间范围无法从问题确定时**省略整个 time_range 字段**（禁止输出空对象）
- calculation: {type: none|yoy|qoq|share|growth|rank, expr: 可选表达式描述}（share 需给分母说明）
- sub_queries: 固定输出 []
- confidence: {metric_confidence: 0~1 你对本次理解把握的自评分}
- ambiguity: {need_clarification: true|false, reason: 需澄清时必填非空，否则空串}

歧义触发规则（need_clarification=true）：问题用词可指多个业务对象；时间范围无法从问题确定；参考指标有多个且语义接近无法判断用户要哪个。
今天日期：{today}（用于推算时间窗起止）。"""


def _collect_stream(res, token_usage: dict) -> tuple[str, str]:
    """流式收集：累积 content 与 reasoning_content（plan 不推 SSE，无需 process_stream 标签解析）。"""
    full_text = ''
    reasoning = ''
    for chunk in res:
        if isinstance(chunk, BaseMessageChunk):
            full_text += chunk.content or ''
            reasoning += (chunk.additional_kwargs or {}).get('reasoning_content', '') or ''
            usage = getattr(chunk, 'usage_metadata', None)
            if isinstance(usage, dict):
                for key in ('input_tokens', 'output_tokens', 'total_tokens'):
                    if usage.get(key):
                        token_usage[key] = token_usage.get(key, 0) + int(usage[key])
    return full_text, reasoning


def _calc_confidence(llm_self: float, metric_candidates: list) -> tuple[float, dict]:
    """混合信号（方案 5.1）：0.60×llm_self + 0.25×recall_gap + 0.15×hit_factor，clamp [0,1]。"""
    llm_self = max(0.0, min(1.0, float(llm_self or 0.0)))
    scores = [float(m.get('recall_score') or 0.0) for m in (metric_candidates or [])]
    hit_factor = 1.0 if scores else 0.6
    if len(scores) >= 2:
        ordered = sorted(scores, reverse=True)
        recall_gap = max(0.0, ordered[0] - ordered[1])
    else:
        recall_gap = 0.0
    confidence = max(0.0, min(1.0, 0.60 * llm_self + 0.25 * recall_gap + 0.15 * hit_factor))
    return confidence, {
        'llm_self': llm_self,
        'recall_gap': round(recall_gap, 4),
        'hit_factor': hit_factor,
    }


def build_query_plan(service, _session) -> QueryPlan | None:
    """生成 Query Plan（开关判断/日志/校验/置信度/异常兜底全包，不向外抛错）。

    service: llm service 实例（读 question/_metric_candidates/llm/record）；调用方 llm.py 仅一行调用（G1）。
    """
    if not settings.QUERY_PLAN_ENABLED:
        return None

    plan: QueryPlan | None = None
    error_msg = ''
    full_text = ''
    reasoning = ''
    token_usage: dict = {}
    log = start_log(session=_session, operate=OperationEnum.QUERY_PLAN,
                    record_id=service.record.id, local_operation=True)
    try:
        question = service.chat_question.question
        metric_candidates = getattr(service, '_metric_candidates', None) or []
        # 候选剥 recall_score 后进提示词（信号分由后端计算，不需 LLM 可见）
        metrics_payload = [{k: v for k, v in m.items() if k != 'recall_score'}
                           for m in metric_candidates]
        messages = [
            # 用 replace 而非 format：提示词含字面 JSON 示例大括号（{metric_name: ...} 等），format 会当格式化字段报 KeyError
            SystemPromptMessage(content=QUERY_PLAN_SYSTEM_PROMPT.replace(
                '{today}', date.today().isoformat())),
            HumanPromptMessage(content=(
                f'用户问题：{question}\n'
                f'参考指标候选（可选用，也允许依据问题补充）：'
                f'{orjson.dumps(metrics_payload).decode()}')),
        ]
        full_text, reasoning = _collect_stream(service.llm.stream(messages), token_usage)

        json_str = extract_nested_json(full_text)
        if not json_str:
            raise ValueError(f'cannot parse plan json from answer: {full_text[:300]}')
        raw: dict = orjson.loads(json_str)
        llm_self = ((raw.get('confidence') or {}).get('metric_confidence')) or 0.0
        validated = QueryPlan.model_validate(raw)  # strict：extra='forbid' + 枚举校验

        confidence, signal_vals = _calc_confidence(llm_self, metric_candidates)
        plan = validated.model_copy(update={
            'confidence': validated.confidence.model_copy(update={
                'metric_confidence': confidence,
                'signals': ConfidenceSignals(**signal_vals),
            }),
        })
    except ValidationError as e:
        error_msg = f'plan schema validation failed: {e.errors()[:3]}'
    except Exception as e:  # noqa: BLE001
        error_msg = f'plan generation failed: {e}'
    finally:
        if error_msg:
            SQLBotLogUtil.error(f'[QUERY-PLAN] {error_msg}', exc_info=True)
            content = orjson.dumps({'status': 'failed', 'error': error_msg[:500]}).decode()
        else:
            content = orjson.dumps({'status': 'ok', 'plan': plan.model_dump(mode='json')}).decode()
        end_log(session=_session, log=log,
                full_message=[{'type': 'ai', 'content': content}],
                reasoning_content=reasoning, token_usage=token_usage)
    return plan


def is_low_confidence(plan: QueryPlan | None) -> bool:
    """低置信判定（决策②b 提示条触发条件；方案 5.3）。"""
    if plan is None:
        return False
    return plan.confidence.metric_confidence < settings.QUERY_PLAN_LOW_CONFIDENCE_THRESHOLD


# ========= 【改造标记 QUERY-PLAN】↑ Query Plan 生成模块结束 =========
