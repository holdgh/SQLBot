"""074_dimension_source_ds

Revision ID: m074dim0001
Revises: m073metric0001
Create Date: 2026-10-13 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'm074dim0001'
down_revision = 'm073metric0001'
branch_labels = None
depends_on = None


def upgrade():
    # ========= 【改造标记 METRIC-CENTER】↓ 074 维度落点三元组（问题 4：数据源/数据表/字段名显式持久化） =========
    # 维度持久化「数据源 + 数据表 + 字段名」三元组，镜像指标表 source_ds_id/source_table 做法；
    # default_column 改名 column_name（"默认字段名"语义不成立，字段对应必须逐表显式，用户拍板）
    op.add_column('dimension', sa.Column('source_ds_id', sa.BigInteger(), nullable=True))
    op.add_column('dimension', sa.Column('source_table', sa.String(length=255), nullable=True))
    op.alter_column('dimension', 'default_column', new_column_name='column_name',
                    existing_type=sa.String(length=255), existing_nullable=True)
    # ========= 【改造标记 METRIC-CENTER】↑ 074 增列/改名结束 =========


def downgrade():
    # ========= 【改造标记 METRIC-CENTER】↓ 074 回滚 =========
    op.alter_column('dimension', 'column_name', new_column_name='default_column',
                    existing_type=sa.String(length=255), existing_nullable=True)
    op.drop_column('dimension', 'source_table')
    op.drop_column('dimension', 'source_ds_id')
    # ========= 【改造标记 METRIC-CENTER】↑ 074 回滚结束 =========
