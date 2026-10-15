"""075_schema_doc

Revision ID: m075schemadoc0001
Revises: m074dim0001
Create Date: 2026-10-13 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
import pgvector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'm075schemadoc0001'
down_revision = 'm074dim0001'
branch_labels = None
depends_on = None


def upgrade():
    # ========= 【改造标记 SCHEMA-DOC】↓ 075 Phase 2 Schema 语义文档三表 =========
    # table_metadata / column_metadata：语义元数据（description 为 G5 预留，MVP 建而不查）
    # schema_document：双粒度语义文档（object_type ∈ TABLE/COLUMN），按 ds_id 隔离
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.create_table(
        'table_metadata',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('ds_id', sa.BigInteger(), nullable=True),
        sa.Column('table_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'column_metadata',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('ds_id', sa.BigInteger(), nullable=True),
        sa.Column('table_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('field_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('alias', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'schema_document',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('ds_id', sa.BigInteger(), nullable=True),
        sa.Column('object_type', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column('object_key', sa.Text(), nullable=True),
        sa.Column('document_text', sa.Text(), nullable=True),
        sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ds_id', 'object_type', 'object_key', name='uq_schema_document_obj'),
    )
    op.create_index('ix_schema_document_ds_type', 'schema_document', ['ds_id', 'object_type'])
    # ========= 【改造标记 SCHEMA-DOC】↑ 075 三表创建结束 =========


def downgrade():
    # ========= 【改造标记 SCHEMA-DOC】↓ 075 回滚 =========
    op.drop_index('ix_schema_document_ds_type', table_name='schema_document')
    op.drop_table('schema_document')
    op.drop_table('column_metadata')
    op.drop_table('table_metadata')
    # ========= 【改造标记 SCHEMA-DOC】↑ 075 回滚结束 =========
