# ========= 【改造标记 CUSTOM-PROMPT】↓ 开源自定义提示词 ORM 模型，替换 sqlbot_xpack 闭源模型（新建文件） =========
from datetime import datetime
from enum import Enum, StrEnum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Identity, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.sqltypes import Enum as SQLAlchemyEnum
from sqlmodel import Field, SQLModel

# ========= 【改造标记 CUSTOM-PROMPT】↓ 共享全局 metadata：必须先让 xpack 注册 custom_prompt 表，
# 本模块随后复用该表对象（xpack 侧未开 extend_existing，反序加载会报 Table already defined） =========
try:
    import sqlbot_xpack.custom_prompt.models.custom_prompt_model  # noqa: F401
except Exception:
    pass
# ========= 【改造标记 CUSTOM-PROMPT】↑ 预加载结束 =========

_existing_table = SQLModel.metadata.tables.get('custom_prompt')


class CustomPromptTypeEnum(StrEnum):
    """类型枚举。

    【改造标记 CUSTOM-PROMPT】↓ enum 跨类绑定修复：xpack 已注册的 custom_prompt.type 列
    其 SQLAlchemyEnum 绑定的是 xpack 自己的 CustomPromptTypeEnum（plain Enum），
    _valid_lookup 只含「xpack 成员 + 字符串值」，直接传本类 plain Enum 成员会 KeyError
    → LookupError（find_custom_prompts 等 where/insert 全挂）。
    改为 StrEnum 后本类成员同时是 str，按 hash/eq 命中字符串键，
    与绑定类无关，读写两侧（读侧仍走 _normalize_prompt_type 归一化）均通过。
    """
    GENERATE_SQL = 'GENERATE_SQL'
    ANALYSIS = 'ANALYSIS'
    PREDICT_DATA = 'PREDICT_DATA'
# 【改造标记 CUSTOM-PROMPT】↑ enum 跨类绑定修复结束


def enum_values(enum_class):
    return [status.value for status in enum_class]


class CustomPrompt(SQLModel, table=True):
    if _existing_table is not None:
        # ========= 【改造标记 CUSTOM-PROMPT】↓ xpack 已注册表：字段直接绑定既有列，避免列对象被替换 =========
        __table__ = _existing_table
        id: int | None = Field(sa_column=_existing_table.columns['id'])
        oid: int | None = Field(sa_column=_existing_table.columns['oid'])
        type: CustomPromptTypeEnum | None = Field(sa_column=_existing_table.columns['type'])
        create_time: datetime | None = Field(sa_column=_existing_table.columns['create_time'])
        name: str | None = Field(sa_column=_existing_table.columns['name'])
        prompt: str | None = Field(sa_column=_existing_table.columns['prompt'])
        specific_ds: bool | None = Field(sa_column=_existing_table.columns['specific_ds'])
        datasource_ids: list[int] | None = Field(sa_column=_existing_table.columns['datasource_ids'], default=[])
        advanced_application: int | None = Field(sa_column=_existing_table.columns['advanced_application'])
        # ========= 【改造标记 CUSTOM-PROMPT】↑ 既有列绑定结束 =========
    else:
        # ========= 【改造标记 CUSTOM-PROMPT】↓ xpack 不在场：按 alembic 046/069 DDL 自建表映射 =========
        __tablename__ = 'custom_prompt'
        id: int | None = Field(sa_column=Column(BigInteger, Identity(always=True), primary_key=True))
        oid: int | None = Field(sa_column=Column(BigInteger, nullable=True, default=1))
        type: CustomPromptTypeEnum | None = Field(
            sa_column=Column(SQLAlchemyEnum(CustomPromptTypeEnum, name='customprompttypeenum',
                                            native_enum=False, length=20, values_callable=enum_values),
                             nullable=True))
        create_time: datetime | None = Field(sa_column=Column(DateTime, nullable=True))
        name: str | None = Field(default=None, max_length=255)
        prompt: str | None = Field(sa_column=Column(Text, nullable=True))
        specific_ds: bool | None = Field(sa_column=Column(Boolean, nullable=True, default=False))
        datasource_ids: list[int] | None = Field(sa_column=Column(JSONB), default=[])
        advanced_application: int | None = Field(sa_column=Column(BigInteger, nullable=True))
        # ========= 【改造标记 CUSTOM-PROMPT】↑ 自建表映射结束 =========


# ========= 【改造标记 CUSTOM-PROMPT】↓ 外类枚举成员（如 xpack CustomPromptTypeEnum）按值归一化：
# pydantic 默认拒绝非本枚举类的 Enum 成员输入 =========
def _normalize_prompt_type(v):
    if isinstance(v, Enum) and not isinstance(v, CustomPromptTypeEnum):
        return getattr(v, 'value', v)
    return v


PromptTypeField = Annotated[CustomPromptTypeEnum, BeforeValidator(_normalize_prompt_type)]
# ========= 【改造标记 CUSTOM-PROMPT】↑ 归一化结束 =========


class CustomPromptInfo(BaseModel):
    id: int | None = None
    oid: int | None = None
    type: PromptTypeField | None = None
    create_time: datetime | None = None
    name: str | None = None
    prompt: str | None = None
    specific_ds: bool | None = False
    datasource_ids: list[int] | None = []
    datasource_names: list[str] | None = []
    advanced_application: int | None = None
    advanced_application_name: str | None = None


class CustomPromptInfoResult(BaseModel):
    id: int | None = None
    oid: int | None = None
    type: PromptTypeField | None = None
    create_time: datetime | None = None
    name: str | None = None
    prompt: str | None = None
    specific_ds: bool | None = False
    datasource_ids: list[int] | None = []
    datasource_names: list[str] | None = []
    advanced_application: str | None = None
    advanced_application_name: str | None = None


class SearchCustomPromptInfo(BaseModel):
    name: str | None = None
    ds_list: list[int] | None = None
    adv_list: list[int] | None = None


# ========= 【改造标记 CUSTOM-PROMPT】↑ 新建文件结束 =========
