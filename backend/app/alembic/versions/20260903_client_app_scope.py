"""客户端应用范围与运营人员授权。

Revision ID: 20260903_client_app_scope
Revises: 20260902_payment_channels
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_client_app_scope"
down_revision: str | None = "20260902_payment_channels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
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
    if not inspector.has_table("client_app"):
        op.create_table(
            "client_app",
            *_base_columns(),
            sa.Column("code", sa.String(64), nullable=False, unique=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("logo", sa.String(255), nullable=True),
            sa.Column("client_version", sa.String(32), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("registration_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True),
            sa.Column("updated_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True),
            sa.Column("deleted_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True),
            comment="客户端应用表",
        )
        op.create_index("ix_client_app_code", "client_app", ["code"], unique=True)
        op.create_index("ix_client_app_name", "client_app", ["name"])
        op.create_index("ix_client_app_status_deleted", "client_app", ["status", "is_deleted"])
        op.create_index("ix_client_app_created_deleted", "client_app", ["created_time", "is_deleted"])
        op.create_index("ix_client_app_created_id", "client_app", ["created_id"])
        op.create_index("ix_client_app_updated_id", "client_app", ["updated_id"])
        op.create_index("ix_client_app_deleted_id", "client_app", ["deleted_id"])

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("sys_user_app"):
        op.create_table(
            "sys_user_app",
            *_base_columns(),
            sa.Column("staff_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.UniqueConstraint("staff_id", "app_id", name="uq_sys_user_app_staff_app"),
            comment="运营人员客户端应用授权表",
        )
        op.create_index("ix_sys_user_app_staff_status", "sys_user_app", ["staff_id", "status", "is_deleted"])
        op.create_index("ix_sys_user_app_app_status", "sys_user_app", ["app_id", "status", "is_deleted"])
        op.create_index("ix_sys_user_app_created_deleted", "sys_user_app", ["created_time", "is_deleted"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("sys_user_app"):
        op.drop_table("sys_user_app")
    if inspector.has_table("client_app"):
        op.drop_table("client_app")
