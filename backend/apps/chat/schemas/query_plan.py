"""Query Plan 结构定义（Phase 4 语义解析层）。

权威规格：v201改造方案_v1.2.md Phase 4 章节；方案分析见 selfdoc/v201/detail/phase4-query-plan方案分析.md。
strict 校验：extra='forbid' + 枚举字面量；校验失败 = plan 回退（不阻断主流程）。
"""
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QueryType = Literal['aggregate', 'detail', 'trend', 'rank', 'compare']
CalculationType = Literal['none', 'yoy', 'qoq', 'share', 'growth', 'rank']
# 五枚举值元组（自动与 QueryType 同步）；五值互不为前缀——前缀归一确定性零误判的依据
QUERY_TYPES: tuple[str, ...] = get_args(QueryType)
# 去尾变形派生（词干变化非前缀关系，compare→comparison、aggregate→aggregation，
# 前缀匹配覆盖不了）——仅收此两族（含复数）；trend 系与 ranking/details 等由前缀覆盖
QUERY_TYPE_ALIASES = {
    'comparison': 'compare',
    'comparisons': 'compare',
    'aggregation': 'aggregate',
    'aggregations': 'aggregate',
}


class TimeWindow(BaseModel):
    """时间窗：ISO 日期字符串（LLM 依据问题与当前日期生成）。"""
    model_config = ConfigDict(extra='forbid')

    start: str = Field(min_length=1)
    end: str = Field(min_length=1)


class TimeRange(BaseModel):
    model_config = ConfigDict(extra='forbid')

    current: TimeWindow
    previous: TimeWindow | None = None


class MetricRef(BaseModel):
    """计划查询的指标引用。"""
    model_config = ConfigDict(extra='forbid')

    metric_name: str = Field(min_length=1)
    aggregation: str | None = None


class FilterItem(BaseModel):
    """业务级过滤描述（不落 SQL 片段，DSL 形态约束）。"""
    model_config = ConfigDict(extra='forbid')

    field: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    value: Any = None
    logic: Literal['and', 'or'] | None = None


class Calculation(BaseModel):
    """计算意图：决定子查询拓扑（Phase 6 消费）；expr 为 share 类分母表达式等可选描述。"""
    model_config = ConfigDict(extra='forbid')

    type: CalculationType = 'none'
    expr: str | None = None


class ConfidenceSignals(BaseModel):
    """混合信号明细（落日志供 Phase 0 调参）。"""
    model_config = ConfigDict(extra='forbid')

    llm_self: float = 0.0
    recall_gap: float = 0.0
    hit_factor: float = 0.0

    @field_validator('llm_self', 'recall_gap', 'hit_factor', mode='before')
    @classmethod
    def _clamp01(cls, v: Any) -> Any:
        if isinstance(v, (int, float)):
            return max(0.0, min(1.0, float(v)))
        return v


class Confidence(BaseModel):
    model_config = ConfigDict(extra='forbid')

    metric_confidence: float = 0.0
    signals: ConfidenceSignals = Field(default_factory=ConfidenceSignals)

    @field_validator('metric_confidence', mode='before')
    @classmethod
    def _clamp01(cls, v: Any) -> Any:
        if isinstance(v, (int, float)):
            return max(0.0, min(1.0, float(v)))
        return v


class Ambiguity(BaseModel):
    """歧义标记（本期仅标记：need_clarification=true 时 reason 必填非空，4.1 校验口径）。"""
    model_config = ConfigDict(extra='forbid')

    need_clarification: bool = False
    reason: str = ''

    @model_validator(mode='after')
    def _reason_required(self) -> 'Ambiguity':
        if self.need_clarification and not (self.reason or '').strip():
            raise ValueError('reason is required and must be non-empty when need_clarification=true')
        return self


class QueryPlan(BaseModel):
    """Query Plan 顶层结构（sub_queries 与自身同构，供 calculation 展开）。"""
    model_config = ConfigDict(extra='forbid')

    query_type: QueryType
    metrics: list[MetricRef] = Field(min_length=1)
    dimensions: list[str] = Field(default_factory=list)
    filters: list[FilterItem] = Field(default_factory=list)
    # 案2（2026-10-22 拍板）：可空——时间无法从问题确定的歧义题（5.2 触发条件）合法省略，
    # 与「4.1 current 必填」原标注的冲突以此为准修正；前端 LogPlan 条件渲染
    time_range: TimeRange | None = None
    calculation: Calculation = Field(default_factory=Calculation)
    sub_queries: list['QueryPlan'] = Field(default_factory=list)
    confidence: Confidence = Field(default_factory=Confidence)
    ambiguity: Ambiguity = Field(default_factory=Ambiguity)

    @model_validator(mode='before')
    @classmethod
    def _normalize_query_type(cls, data: Any) -> Any:
        # 问题 13 方案 1（2026-10-23 拍板，2026-10-26 实施）：LLM（弱模型）按题面英译
        # 惯性输出 query_type 漂移（实测 tr end/trending/trends 全在 trend 家族）→
        # 语义归一收口，三级：lower+去内部空格 → 精确命中用；未命中过词干变形别名表
        # （comparison/aggregation）；仍未命中取「枚举值是输入前缀」的合法值（五枚举
        # 互不为前缀，确定性零误判）；都不中保持原值交 strict 拒绝（失败回退语义不变）。
        # 兼容弱模型与将来强模型。
        if isinstance(data, dict):
            qt = data.get('query_type')
            if isinstance(qt, str):
                norm = ''.join(qt.strip().lower().split())
                if norm not in QUERY_TYPES:
                    norm = QUERY_TYPE_ALIASES.get(norm, norm)
                if norm not in QUERY_TYPES:
                    for legal in QUERY_TYPES:
                        if norm.startswith(legal):
                            norm = legal
                            break
                if norm != qt:
                    data = {**data, 'query_type': norm}
        return data

    @model_validator(mode='before')
    @classmethod
    def _normalize_empty_time_range(cls, data: Any) -> Any:
        # 问题 12 方案 A（2026-10-23 拍板，实现层容错）：LLM 偶发输出空壳
        # time_range（current 为 null 或缺 start/end）→ 按案2「时间未确定=省略整个字段」
        # 语义整体归一为 None，避免 strict 校验失败将 plan 误判 failed。
        if isinstance(data, dict):
            tr = data.get('time_range')
            if isinstance(tr, dict):
                cur = tr.get('current')
                cur_empty = cur is None or (isinstance(cur, dict) and (not cur.get('start') or not cur.get('end')))
                prev = tr.get('previous')
                prev_empty = prev is not None and (not isinstance(prev, dict)
                                                   or (not prev.get('start') or not prev.get('end')))
                if cur_empty:
                    data = {**data, 'time_range': None}
                elif prev_empty:
                    data = {**data, 'time_range': {**tr, 'previous': None}}
        return data


QueryPlan.model_rebuild()
