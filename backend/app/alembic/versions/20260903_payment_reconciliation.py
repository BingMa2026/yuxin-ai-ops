"""支付主动查单、尝试审计与回调摘要。

Revision ID: 20260903_payment_reconcile
Revises: 20260903_telemetry_events
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_payment_reconcile"
down_revision: str | None = "20260903_telemetry_events"
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
    callback_columns = {column["name"] for column in inspector.get_columns("payment_callback")}
    if "payload_digest" not in callback_columns:
        op.add_column("payment_callback", sa.Column("payload_digest", sa.String(64), nullable=True))

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("payment_attempt"):
        op.create_table(
            "payment_attempt",
            *_base(),
            sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("payment_order.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("order_no", sa.String(64), nullable=False),
            sa.Column("provider", sa.String(20), nullable=False),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("error_message", sa.String(500), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            comment="支付渠道下单与主动查单尝试",
        )
        op.create_index("ix_payment_attempt_app_order", "payment_attempt", ["app_id", "order_id", "created_time"])
        op.create_index("ix_payment_attempt_provider_status", "payment_attempt", ["provider", "status", "created_time"])
        op.create_index("ix_payment_attempt_created_deleted", "payment_attempt", ["created_time", "is_deleted"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("payment_attempt"):
        op.drop_table("payment_attempt")
    inspector = sa.inspect(op.get_bind())
    callback_columns = {column["name"] for column in inspector.get_columns("payment_callback")}
    if "payload_digest" in callback_columns:
        op.drop_column("payment_callback", "payload_digest")
