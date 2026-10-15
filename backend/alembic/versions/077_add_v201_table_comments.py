"""077_add_v201_table_comments

为 Phase 1/2 改造新建的 9 张表补充表/字段中文注释（COMMENT ON）。
沿用 070 迁移的 _COMMENTS 字典模式。
Revision ID: m077comments0001
Revises: m076metadataunique0001
Create Date: 2026-10-15 17:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'm077comments0001'
down_revision = 'm076metadataunique0001'
branch_labels = None
depends_on = None

# 表和列备注定义：key 为 "表名" 或 "表名.列名"，value 为备注文本
# 覆盖 Phase 1（072/073/074）与 Phase 2（075）新建表；列清单为 073/074 变更后的最终形态
_COMMENTS = {
    # ========== metric_definition 指标定义表（072 建表 + 073 增 source_ds_id） ==========
    'metric_definition': '指标定义表（指标中心核心表，一行=一个业务指标的口径定义）',
    'metric_definition.id': '主键ID',
    'metric_definition.oid': '组织ID',
    'metric_definition.create_time': '创建时间',
    'metric_definition.metric_name': '指标名称（业务口径名，如：游客总人数）',
    'metric_definition.description': '指标业务描述',
    'metric_definition.business_domain': '业务域（指标分类，如：客流、营收）',
    'metric_definition.specific_ds': '是否指定数据源（true=限定 datasource_ids，false=全数据源可用）',
    'metric_definition.datasource_ids': '适用数据源ID列表（JSONB 数组，specific_ds=true 时生效）',
    'metric_definition.source_table': '指标计算来源表名',
    'metric_definition.source_column': '指标计算来源字段名',
    'metric_definition.source_ds_id': '来源数据源ID（073 新增：来源表归属的数据源，供前端级联与 Phase 5 编译定位）',
    'metric_definition.aggregation': '聚合方式（SUM/COUNT/AVG/MAX/MIN 等）',
    'metric_definition.filter_rule': '过滤规则（SQL 条件表达式）',
    'metric_definition.time_field': '时间字段名（时间范围过滤所用列）',
    'metric_definition.metric_type': '指标类型',
    'metric_definition.unit': '计量单位',
    'metric_definition.normal_range': '正常值范围（JSONB，含 min/max）',
    'metric_definition.additivity': '可加性（可加/不可加，影响分组汇总口径）',
    'metric_definition.status': '状态（enabled/disabled）',
    'metric_definition.version': '版本号',

    # ========== metric_alias 指标别名表（072） ==========
    'metric_alias': '指标别名表（同一指标的同义词/口语化叫法，供术语匹配）',
    'metric_alias.id': '主键ID',
    'metric_alias.metric_id': '指标定义ID（外键→metric_definition.id）',
    'metric_alias.alias': '别名文本',

    # ========== metric_document 指标语义文档表（072） ==========
    'metric_document': '指标语义文档表（指标的向量化描述文本，供相似度召回）',
    'metric_document.id': '主键ID',
    'metric_document.metric_id': '指标定义ID（外键→metric_definition.id）',
    'metric_document.document_text': '语义描述文档原文',
    'metric_document.embedding': '文档向量（pgvector）',
    'metric_document.keyword_list': '关键词列表（JSONB 数组）',

    # ========== dimension 维度定义表（072 建表 + 074 落点三元组） ==========
    'dimension': '维度定义表（分析维度，如：来源地、时间段；074 起持久化数据源/表/字段落点三元组）',
    'dimension.id': '主键ID',
    'dimension.oid': '组织ID',
    'dimension.create_time': '创建时间',
    'dimension.dimension_name': '维度名称（如：游客来源地）',
    'dimension.aliases': '别名列表（JSONB 数组）',
    'dimension.column_name': '落点字段名（074 由 default_column 改名：维度对应的具体数据库列）',
    'dimension.description': '维度业务描述',
    'dimension.source_ds_id': '来源数据源ID（074 新增）',
    'dimension.source_table': '来源数据表名（074 新增）',

    # ========== metric_dimension_relation 指标-维度关联表（072） ==========
    'metric_dimension_relation': '指标-维度关联表（记录哪些维度可用于哪些指标的分析）',
    'metric_dimension_relation.id': '主键ID',
    'metric_dimension_relation.metric_id': '指标定义ID',
    'metric_dimension_relation.dimension_id': '维度定义ID',
    'metric_dimension_relation.enabled': '是否启用',

    # ========== metric_dependency 指标依赖表（072） ==========
    'metric_dependency': '指标依赖表（派生指标对其基础指标的依赖关系）',
    'metric_dependency.id': '主键ID',
    'metric_dependency.derived_metric_id': '派生指标ID',
    'metric_dependency.depends_on_metric_id': '被依赖的基础指标ID',
    'metric_dependency.expression_hint': '组合表达式提示（派生指标的计算表达式说明）',

    # ========== table_metadata 表语义档案（075，G5 预留建而不查） ==========
    'table_metadata': '表语义档案（Phase 2 G5 预留：表级人工描述，当前不参与检索）',
    'table_metadata.id': '主键ID',
    'table_metadata.ds_id': '数据源ID',
    'table_metadata.table_name': '表名',
    'table_metadata.description': '表业务描述（G5 预留，当前为空）',
    'table_metadata.create_time': '创建时间',

    # ========== column_metadata 字段语义档案（075，G5 预留建而不查） ==========
    'column_metadata': '字段语义档案（Phase 2 G5 预留：字段级别名/描述，当前不参与检索）',
    'column_metadata.id': '主键ID',
    'column_metadata.ds_id': '数据源ID',
    'column_metadata.table_name': '表名',
    'column_metadata.field_name': '字段名',
    'column_metadata.alias': '字段别名列表（JSONB 预留，当前为空；别名主入口仍是术语库）',
    'column_metadata.description': '字段业务描述（G5 预留，当前为空）',
    'column_metadata.create_time': '创建时间',

    # ========== schema_document Schema 语义文档表（075，Phase 2 检索本体） ==========
    'schema_document': 'Schema语义文档表（Phase 2 检索本体：表/字段双粒度语义文档，供 pgvector 相似度选表）',
    'schema_document.id': '主键ID',
    'schema_document.ds_id': '数据源ID',
    'schema_document.object_type': '对象类型（TABLE=表级文档 / COLUMN=字段级文档）',
    'schema_document.object_key': '对象键（TABLE 用表名；COLUMN 用"表名.字段名"）',
    'schema_document.document_text': '语义描述文档原文',
    'schema_document.embedding': '文档向量（pgvector，文本变更时重置待重算）',
    'schema_document.create_time': '创建时间',
}


def _escape_comment(comment):
    return comment.replace("'", "''")


def _apply_table_comment(table, comment):
    if comment is None:
        op.execute(f"COMMENT ON TABLE {table} IS NULL")
    else:
        op.execute(f"COMMENT ON TABLE {table} IS '{_escape_comment(comment)}'")


def _apply_column_comment(table, column, comment):
    if comment is None:
        op.execute(f"COMMENT ON COLUMN {table}.{column} IS NULL")
    else:
        op.execute(f"COMMENT ON COLUMN {table}.{column} IS '{_escape_comment(comment)}'")


def upgrade():
    # ========= 【改造标记 METRIC-CENTER,SCHEMA-DOC】↓ 077 Phase 1/2 新表补注释 =========
    """为 Phase 1/2 新建的 9 张表和字段添加中文备注"""
    table_keys = sorted(k for k in _COMMENTS if '.' not in k)
    column_keys = sorted(k for k in _COMMENTS if '.' in k)

    for table in table_keys:
        _apply_table_comment(table, _COMMENTS[table])

    for key in column_keys:
        table, column = key.split('.', 1)
        _apply_column_comment(table, column, _COMMENTS[key])
    # ========= 【改造标记 METRIC-CENTER,SCHEMA-DOC】↑ 077 注释添加结束 =========


def downgrade():
    # ========= 【改造标记 METRIC-CENTER,SCHEMA-DOC】↓ 077 回滚 =========
    """移除所有表和字段的备注"""
    table_keys = sorted((k for k in _COMMENTS if '.' not in k), reverse=True)
    column_keys = sorted((k for k in _COMMENTS if '.' in k), reverse=True)

    for key in column_keys:
        table, column = key.split('.', 1)
        _apply_column_comment(table, column, None)

    for table in table_keys:
        _apply_table_comment(table, None)
    # ========= 【改造标记 METRIC-CENTER,SCHEMA-DOC】↑ 077 回滚结束 =========
