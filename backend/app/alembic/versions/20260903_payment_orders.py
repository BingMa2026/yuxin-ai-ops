"""客户端支付订单与幂等回调。

Revision ID: 20260903_payment_orders
Revises: 20260903_model_gateway
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_payment_orders"
down_revision: str | None = "20260903_model_gateway"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(64), nullable=False, unique=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("payment_order"):
        op.create_table(
            "payment_order",
            *_base(),
            sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("order_no", sa.String(64), nullable=False),
            sa.Column("idempotency_key", sa.String(128), nullable=False),
            sa.Column("catalog_plan_id", sa.Integer(), sa.ForeignKey("app_catalog_plan.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("purchase_type", sa.String(20), nullable=False),
            sa.Column("provider", sa.String(20), nullable=False),
            sa.Column("amount_fen", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(8), nullable=False, server_default="CNY"),
            sa.Column("plan_snapshot", sa.JSON(), nullable=False),
            sa.Column("strategy_snapshot", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="created"),
            sa.Column("pay_url", sa.Text(), nullable=True),
            sa.Column("provider_trade_no", sa.String(128), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failure_reason", sa.String(500), nullable=True),
            sa.Column("auto_renew_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.UniqueConstraint("order_no", name="uq_payment_order_no"),
            sa.UniqueConstraint("app_id", "user_id", "idempotency_key", name="uq_payment_order_idempotency"),
            comment="客户端支付订单",
        )
        op.create_index("ix_payment_order_app_status", "payment_order", ["app_id", "status", "created_time"])
        op.create_index("ix_payment_order_app_user", "payment_order", ["app_id", "user_id", "created_time"])
        op.create_index("ix_payment_order_created_deleted", "payment_order", ["created_time", "is_deleted"])
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("payment_callback"):
        op.create_table(
            "payment_callback",
            *_base(),
            sa.Column("provider", sa.String(20), nullable=False),
            sa.Column("callback_id", sa.String(128), nullable=False),
            sa.Column("order_no", sa.String(64), nullable=False),
            sa.Column("provider_trade_no", sa.String(128), nullable=True),
            sa.Column("amount_fen", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="received"),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failure_reason", sa.String(500), nullable=True),
            sa.UniqueConstraint("provider", "callback_id", name="uq_payment_callback_provider_id"),
            comment="支付回调去重与审计（不保存密钥）",
        )
        op.create_index("ix_payment_callback_order", "payment_callback", ["order_no", "status"])
        op.create_index("ix_payment_callback_created_deleted", "payment_callback", ["created_time", "is_deleted"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("payment_callback"):
        op.drop_table("payment_callback")
    if inspector.has_table("payment_order"):
        op.drop_table("payment_order")
