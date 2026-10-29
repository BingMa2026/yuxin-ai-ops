"""支付查单计划与渠道交易号唯一约束。"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_payment_recovery"
down_revision = "20260923_client_wechat_login"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not op.get_context().as_sql:
        duplicate = bind.execute(
            sa.text("SELECT provider, provider_trade_no FROM payment_order WHERE provider_trade_no IS NOT NULL GROUP BY provider, provider_trade_no HAVING COUNT(*) > 1 LIMIT 1")
        ).first()
        if duplicate:
            raise RuntimeError("存在渠道交易号重复的历史订单，需先核对资金与权益再执行迁移")
    op.add_column("payment_order", sa.Column("next_query_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payment_order", sa.Column("query_attempts", sa.Integer(), server_default="0", nullable=False))
    with op.batch_alter_table("payment_order") as batch:
        batch.create_unique_constraint("uq_payment_order_provider_trade", ["provider", "provider_trade_no"])
    op.create_index("ix_payment_order_recovery", "payment_order", ["app_id", "status", "next_query_at"])


def downgrade():
    op.drop_index("ix_payment_order_recovery", table_name="payment_order")
    with op.batch_alter_table("payment_order") as batch:
        batch.drop_constraint("uq_payment_order_provider_trade", type_="unique")
    op.drop_column("payment_order", "query_attempts")
    op.drop_column("payment_order", "next_query_at")
