"""客户端可靠运营遥测事件。

Revision ID: 20260903_telemetry_events
Revises: 20260903_payment_orders
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_telemetry_events"
down_revision: str | None = "20260903_payment_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("telemetry_event"):
        return
    op.create_table(
        "telemetry_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(64), nullable=False, unique=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("client_version", sa.String(64), nullable=True),
        sa.Column("session_ref", sa.String(128), nullable=True),
        sa.Column("project_ref", sa.String(128), nullable=True),
        sa.Column("task_ref", sa.String(128), nullable=True),
        sa.Column("critical", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.UniqueConstraint("app_id", "event_id", name="uq_telemetry_event_app_event"),
        comment="客户端运营遥测事件（不保存业务正文与本地路径）",
    )
    op.create_index("ix_telemetry_event_app_type_time", "telemetry_event", ["app_id", "event_type", "occurred_at"])
    op.create_index("ix_telemetry_event_app_user_time", "telemetry_event", ["app_id", "user_id", "occurred_at"])
    op.create_index("ix_telemetry_event_created_deleted", "telemetry_event", ["created_time", "is_deleted"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("telemetry_event"):
        op.drop_table("telemetry_event")
