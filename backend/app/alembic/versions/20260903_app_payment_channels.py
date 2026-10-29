"""客户端应用支付渠道绑定。

Revision ID: 20260903_app_pay_channels
Revises: 20260903_payment_reconcile
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_app_pay_channels"
down_revision: str | None = "20260903_payment_reconcile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("app_payment_channel"):
        return
    op.create_table(
        "app_payment_channel",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(64), nullable=False, unique=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("pay_channel.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("app_id", "channel_id", name="uq_app_payment_channel"),
        comment="客户端应用支付渠道绑定表",
    )
    op.create_index(
        "ix_app_payment_channel_app_enabled",
        "app_payment_channel",
        ["app_id", "enabled", "is_deleted"],
    )
    op.create_index(
        "ix_app_payment_channel_created_deleted",
        "app_payment_channel",
        ["created_time", "is_deleted"],
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("app_payment_channel"):
        op.drop_table("app_payment_channel")
