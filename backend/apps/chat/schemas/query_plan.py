"""Query Plan 结构定义（Phase 4 语义解析层）。

权威规格：v201改造方案_v1.2.md Phase 4 章节；方案分析见 selfdoc/v201/detail/phase4-query-plan方案分析.md。
strict 校验：extra='forbid' + 枚举字面量；校验失败 = plan 回退（不阻断主流程）。
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QueryType = Literal['aggregate', 'detail', 'trend', 'rank', 'compare']
CalculationType = Literal['none', 'yoy', 'qoq', 'share', 'growth', 'rank']


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


QueryPlan.model_rebuild()
