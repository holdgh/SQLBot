"""072_metric_center

Revision ID: m072metric0001
Revises: a2e2ecfa5a9c
Create Date: 2026-10-09 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
import pgvector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'm072metric0001'
down_revision = 'a2e2ecfa5a9c'
branch_labels = None
depends_on = None


def upgrade():
    # ========= 【改造标记 METRIC-CENTER】↓ 072 指标中心建表（只增不改，可回滚） =========
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.create_table(
        'metric_definition',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('oid', sa.BigInteger(), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=True),
        sa.Column('metric_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('business_domain', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('specific_ds', sa.Boolean(), nullable=True),
        sa.Column('datasource_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('source_table', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('source_column', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('aggregation', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column('filter_rule', sa.Text(), nullable=True),
        sa.Column('time_field', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('metric_type', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column('unit', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column('normal_range', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('additivity', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column('version', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_metric_definition_oid', 'metric_definition', ['oid'])

    op.create_table(
        'metric_alias',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('metric_id', sa.BigInteger(), nullable=True),
        sa.Column('alias', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_metric_alias_metric_id', 'metric_alias', ['metric_id'])

    op.create_table(
        'metric_document',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('metric_id', sa.BigInteger(), nullable=True),
        sa.Column('document_text', sa.Text(), nullable=True),
        sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(), nullable=True),
        sa.Column('keyword_list', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_metric_document_metric_id', 'metric_document', ['metric_id'])

    op.create_table(
        'dimension',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('oid', sa.BigInteger(), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=True),
        sa.Column('dimension_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('aliases', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('default_column', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_dimension_oid', 'dimension', ['oid'])

    op.create_table(
        'metric_dimension_relation',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('metric_id', sa.BigInteger(), nullable=True),
        sa.Column('dimension_id', sa.BigInteger(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_metric_dimension_relation_metric_id', 'metric_dimension_relation', ['metric_id'])
    op.create_index('ix_metric_dimension_relation_dimension_id', 'metric_dimension_relation', ['dimension_id'])

    op.create_table(
        'metric_dependency',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('derived_metric_id', sa.BigInteger(), nullable=True),
        sa.Column('depends_on_metric_id', sa.BigInteger(), nullable=True),
        sa.Column('expression_hint', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_metric_dependency_derived_metric_id', 'metric_dependency', ['derived_metric_id'])
    # ========= 【改造标记 METRIC-CENTER】↑ 072 指标中心建表结束 =========


def downgrade():
    # ========= 【改造标记 METRIC-CENTER】↓ 072 回滚 =========
    op.drop_table('metric_dependency')
    op.drop_table('metric_dimension_relation')
    op.drop_table('dimension')
    op.drop_table('metric_document')
    op.drop_table('metric_alias')
    op.drop_table('metric_definition')
    # ========= 【改造标记 METRIC-CENTER】↑ 072 回滚结束 =========
