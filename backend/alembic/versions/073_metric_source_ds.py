"""073_metric_source_ds

Revision ID: m073metric0001
Revises: m072metric0001
Create Date: 2026-10-10 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'm073metric0001'
down_revision = 'm072metric0001'
branch_labels = None
depends_on = None


def upgrade():
    # ========= 【改造标记 METRIC-CENTER】↓ 073 指标表所属数据源（只增列，可回滚） =========
    # 问题 2 方案 A：记录 source_table 归属哪个数据源，供前端级联与 Phase 5 编译取表结构定位
    op.add_column('metric_definition', sa.Column('source_ds_id', sa.BigInteger(), nullable=True))
    # ========= 【改造标记 METRIC-CENTER】↑ 073 增列结束 =========


def downgrade():
    # ========= 【改造标记 METRIC-CENTER】↓ 073 回滚 =========
    op.drop_column('metric_definition', 'source_ds_id')
    # ========= 【改造标记 METRIC-CENTER】↑ 073 回滚结束 =========
