"""076_metadata_unique

Revision ID: m076metadataunique0001
Revises: m075schemadoc0001
Create Date: 2026-10-15 10:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'm076metadataunique0001'
down_revision = 'm075schemadoc0001'
branch_labels = None
depends_on = None


def upgrade():
    # ========= 【改造标记 SCHEMA-DOC】↓ 076 metadata 双表唯一约束 =========
    # 背景：075 未加唯一约束，apply-schema-docs 曾因批次内去重缺口产生重复行（表 12 条/应 2 条）
    # 先清存量重复（每组保留最小 id），再加唯一约束兜底
    op.execute("""
        DELETE FROM table_metadata a USING table_metadata b
        WHERE a.ds_id IS NOT DISTINCT FROM b.ds_id
          AND a.table_name IS NOT DISTINCT FROM b.table_name
          AND a.id > b.id;
    """)
    op.execute("""
        DELETE FROM column_metadata a USING column_metadata b
        WHERE a.ds_id IS NOT DISTINCT FROM b.ds_id
          AND a.table_name IS NOT DISTINCT FROM b.table_name
          AND a.field_name IS NOT DISTINCT FROM b.field_name
          AND a.id > b.id;
    """)
    op.create_unique_constraint('uq_table_metadata_ds_table', 'table_metadata',
                                ['ds_id', 'table_name'])
    op.create_unique_constraint('uq_column_metadata_ds_table_field', 'column_metadata',
                                ['ds_id', 'table_name', 'field_name'])
    # ========= 【改造标记 SCHEMA-DOC】↑ 076 唯一约束添加结束 =========


def downgrade():
    # ========= 【改造标记 SCHEMA-DOC】↓ 076 回滚 =========
    op.drop_constraint('uq_column_metadata_ds_table_field', 'column_metadata', type_='unique')
    op.drop_constraint('uq_table_metadata_ds_table', 'table_metadata', type_='unique')
    # ========= 【改造标记 SCHEMA-DOC】↑ 076 回滚结束 =========
