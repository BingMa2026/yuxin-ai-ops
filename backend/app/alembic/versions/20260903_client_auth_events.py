"""客户端认证安全事件。

Revision ID: 20260903_client_auth_events
Revises: 20260903_app_pay_channels
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_client_auth_events"
down_revision: str | None = "20260903_app_pay_channels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("client_auth_event"):
        return
    op.create_table(
        "client_auth_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(64), nullable=False, unique=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("app_code", sa.String(64), nullable=False),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("failure_reason", sa.String(255), nullable=True),
        sa.Column("request_ip", sa.String(50), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        comment="客户端注册登录安全事件",
    )
    op.create_index(
        "ix_client_auth_event_app_action_time",
        "client_auth_event",
        ["app_id", "action", "created_time"],
    )
    op.create_index(
        "ix_client_auth_event_ip_time",
        "client_auth_event",
        ["request_ip", "created_time"],
    )
    op.create_index(
        "ix_client_auth_event_username_time",
        "client_auth_event",
        ["app_code", "username", "created_time"],
    )
    op.create_index(
        "ix_client_auth_event_created_deleted",
        "client_auth_event",
        ["created_time", "is_deleted"],
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("client_auth_event"):
        op.drop_table("client_auth_event")
