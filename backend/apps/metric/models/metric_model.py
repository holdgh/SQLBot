# ========= 【改造标记 METRIC-CENTER】↓ 指标中心数据模型（Phase 1，镜像 terminology_model.py） =========
from datetime import datetime
from typing import List, Optional

from pgvector.sqlalchemy import VECTOR
from pydantic import BaseModel
from sqlalchemy import Column, Text, BigInteger, DateTime, Identity, Boolean, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import SQLModel, Field


class MetricDefinition(SQLModel, table=True):
    __tablename__ = "metric_definition"
    id: Optional[int] = Field(sa_column=Column(BigInteger, Identity(always=True), primary_key=True))
    oid: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True, default=1))
    create_time: Optional[datetime] = Field(sa_column=Column(DateTime(timezone=False), nullable=True))
    metric_name: Optional[str] = Field(max_length=255)
    description: Optional[str] = Field(sa_column=Column(Text, nullable=True))
    business_domain: Optional[str] = Field(max_length=255, nullable=True)
    specific_ds: Optional[bool] = Field(sa_column=Column(Boolean, default=False))
    datasource_ids: Optional[list[int]] = Field(sa_column=Column(JSONB), default=[])
    # ========= 【改造标记 METRIC-CENTER】↓ 问题2方案A：source_table 归属的数据源（073 增列） =========
    source_ds_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))
    # ========= 【改造标记 METRIC-CENTER】↑ 增列结束 =========
    source_table: Optional[str] = Field(max_length=255, nullable=True)
    source_column: Optional[str] = Field(max_length=255, nullable=True)
    aggregation: Optional[str] = Field(max_length=64, nullable=True)
    filter_rule: Optional[str] = Field(sa_column=Column(Text, nullable=True))
    time_field: Optional[str] = Field(max_length=255, nullable=True)
    metric_type: Optional[str] = Field(max_length=32, nullable=True)  # atomic/derived/composite，默认 atomic
    unit: Optional[str] = Field(max_length=64, nullable=True)
    normal_range: Optional[dict] = Field(sa_column=Column(JSONB, nullable=True))  # {"min":..,"max":..}
    additivity: Optional[str] = Field(max_length=32, nullable=True)  # additive/semi/non，默认 additive
    status: Optional[str] = Field(max_length=32, nullable=True)  # active/disabled
    version: Optional[int] = Field(sa_column=Column(Integer, nullable=True, default=1))


class MetricAlias(SQLModel, table=True):
    __tablename__ = "metric_alias"
    id: Optional[int] = Field(sa_column=Column(BigInteger, Identity(always=True), primary_key=True))
    metric_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))
    alias: Optional[str] = Field(max_length=255, nullable=True)


class MetricDocument(SQLModel, table=True):
    __tablename__ = "metric_document"
    id: Optional[int] = Field(sa_column=Column(BigInteger, Identity(always=True), primary_key=True))
    metric_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))
    document_text: Optional[str] = Field(sa_column=Column(Text, nullable=True))
    embedding: Optional[List[float]] = Field(sa_column=Column(VECTOR(), nullable=True))
    keyword_list: Optional[list] = Field(sa_column=Column(JSONB, nullable=True))  # 预留不物化


class Dimension(SQLModel, table=True):
    __tablename__ = "dimension"
    id: Optional[int] = Field(sa_column=Column(BigInteger, Identity(always=True), primary_key=True))
    oid: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True, default=1))
    create_time: Optional[datetime] = Field(sa_column=Column(DateTime(timezone=False), nullable=True))
    dimension_name: Optional[str] = Field(max_length=255)
    aliases: Optional[list] = Field(sa_column=Column(JSONB), default=[])
    # ========= 【改造标记 METRIC-CENTER】↓ 问题4：维度落点三元组（074：数据源/数据表 + default_column 改名 column_name） =========
    source_ds_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))
    source_table: Optional[str] = Field(max_length=255, nullable=True)
    column_name: Optional[str] = Field(max_length=255, nullable=True)
    # ========= 【改造标记 METRIC-CENTER】↑ 问题4 增列/改名结束（原 default_column 单值语义废弃） =========
    description: Optional[str] = Field(sa_column=Column(Text, nullable=True))


class MetricDimensionRelation(SQLModel, table=True):
    __tablename__ = "metric_dimension_relation"
    id: Optional[int] = Field(sa_column=Column(BigInteger, Identity(always=True), primary_key=True))
    metric_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))
    dimension_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))
    enabled: Optional[bool] = Field(sa_column=Column(Boolean, default=True))


class MetricDependency(SQLModel, table=True):
    __tablename__ = "metric_dependency"
    id: Optional[int] = Field(sa_column=Column(BigInteger, Identity(always=True), primary_key=True))
    derived_metric_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))
    depends_on_metric_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))
    expression_hint: Optional[str] = Field(sa_column=Column(Text, nullable=True))


# ========= 【改造标记 TRUST-VALIDATE】↓ Phase 3 指标口径校验规则（078 建表） =========
class MetricRule(SQLModel, table=True):
    __tablename__ = "metric_rule"
    id: Optional[int] = Field(sa_column=Column(BigInteger, Identity(always=True), primary_key=True))
    metric_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))
    rule_type: Optional[str] = Field(max_length=32, nullable=True)  # required_filter/forbidden_field/forced_agg
    rule_content: Optional[str] = Field(sa_column=Column(Text, nullable=True))
    status: Optional[bool] = Field(sa_column=Column(Boolean, default=True))
    create_time: Optional[datetime] = Field(sa_column=Column(DateTime(timezone=False), nullable=True))
# ========= 【改造标记 TRUST-VALIDATE】↑ Phase 3 规则模型结束 =========


class MetricDependencyInfo(BaseModel):
    depends_on_metric_id: Optional[int] = None
    depends_on_metric_name: Optional[str] = None
    expression_hint: Optional[str] = None


class MetricInfo(BaseModel):
    """前端表单载体（含别名/关联维度/依赖指标）"""
    id: Optional[int] = None
    create_time: Optional[datetime] = None
    metric_name: Optional[str] = None
    description: Optional[str] = None
    business_domain: Optional[str] = None
    specific_ds: Optional[bool] = False
    datasource_ids: Optional[list[int]] = []
    datasource_names: Optional[list[str]] = []
    # ========= 【改造标记 METRIC-CENTER】↓ 问题2方案A：表所属数据源 =========
    source_ds_id: Optional[int] = None
    # ========= 【改造标记 METRIC-CENTER】↑ 增列结束 =========
    source_table: Optional[str] = None
    source_column: Optional[str] = None
    aggregation: Optional[str] = None
    filter_rule: Optional[str] = None
    time_field: Optional[str] = None
    metric_type: Optional[str] = "atomic"
    unit: Optional[str] = None
    normal_range: Optional[dict] = None
    additivity: Optional[str] = "additive"
    status: Optional[str] = "active"
    version: Optional[int] = 1
    enabled: Optional[bool] = True
    aliases: Optional[List[str]] = []
    dimension_ids: Optional[List[int]] = []
    dimension_names: Optional[List[str]] = []
    dependencies: Optional[List[MetricDependencyInfo]] = []


class MetricInfoResult(MetricInfo):
    """列表/详情返回（维度名与依赖指标名已解析）"""
    pass


class DimensionInfo(BaseModel):
    id: Optional[int] = None
    create_time: Optional[datetime] = None
    dimension_name: Optional[str] = None
    aliases: Optional[List[str]] = []
    # ========= 【改造标记 METRIC-CENTER】↓ 问题4：维度落点三元组 =========
    source_ds_id: Optional[int] = None
    source_table: Optional[str] = None
    column_name: Optional[str] = None
    # ========= 【改造标记 METRIC-CENTER】↑ 问题4 结束（原 default_column） =========
    description: Optional[str] = None
    metric_count: Optional[int] = 0


class DimensionInfoResult(DimensionInfo):
    pass
# ========= 【改造标记 METRIC-CENTER】↑ 指标中心数据模型结束 =========
