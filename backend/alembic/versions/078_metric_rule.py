"""078_metric_rule

Phase 3-A 指标口径校验规则表（告警级，G4 先观测后阻断）。
唯一约束吸取 076 教训直接建齐；表/字段中文注释沿用 077 规范。

Revision ID: m078metricrule0001
Revises: m077comments0001
Create Date: 2026-10-16 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision = 'm078metricrule0001'
down_revision = 'm077comments0001'
branch_labels = None
depends_on = None


def upgrade():
    # ========= 【改造标记 TRUST-VALIDATE】↓ 078 Phase 3 指标口径规则表 =========
    op.create_table(
        'metric_rule',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('metric_id', sa.BigInteger(), nullable=True),
        sa.Column('rule_type', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column('rule_content', sa.Text(), nullable=True),
        sa.Column('status', sa.Boolean(), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('metric_id', 'rule_type', 'rule_content', name='uq_metric_rule_type_content'),
    )
    op.execute("COMMENT ON TABLE metric_rule IS '指标口径校验规则表（Phase 3-A 告警级：违规仅产生告警日志不阻断，阻断级 Phase 5 随 plan 强绑定启用）'")
    op.execute("COMMENT ON COLUMN metric_rule.metric_id IS '所属指标ID（metric_definition.id）'")
    op.execute("COMMENT ON COLUMN metric_rule.rule_type IS '规则类型：required_filter=必带过滤字段 / forbidden_field=禁用字段 / forced_agg=强制聚合函数'")
    op.execute("COMMENT ON COLUMN metric_rule.rule_content IS '规则内容：required_filter/forbidden_field 为逗号/顿号/空格分隔的字段列表；forced_agg 为单个聚合函数名（sum/count/avg/max/min）'")
    op.execute("COMMENT ON COLUMN metric_rule.status IS '是否启用（默认 true，空值按启用处理）'")
    op.execute("COMMENT ON COLUMN metric_rule.create_time IS '创建时间'")
    # ========= 【改造标记 TRUST-VALIDATE】↑ 078 创建结束 =========


def downgrade():
    # ========= 【改造标记 TRUST-VALIDATE】↓ 078 回滚 =========
    op.drop_table('metric_rule')
    # ========= 【改造标记 TRUST-VALIDATE】↑ 078 回滚结束 =========
