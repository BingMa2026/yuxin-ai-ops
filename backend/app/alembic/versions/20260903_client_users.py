"""客户端最终用户与人工标签。

Revision ID: 20260903_client_users
Revises: 20260903_client_app_scope
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_client_users"
down_revision: str | None = "20260903_client_app_scope"
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


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True),
        sa.Column("updated_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True),
        sa.Column("deleted_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True),
    ]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("client_user"):
        op.create_table(
            "client_user",
            *_base_columns(),
            sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("username", sa.String(32), nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("display_name", sa.String(64), nullable=True),
            sa.Column("company_name", sa.String(128), nullable=True),
            sa.Column("mobile", sa.String(20), nullable=True),
            sa.Column("email", sa.String(128), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("auth_generation", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("registration_source", sa.String(32), nullable=False, server_default="self"),
            sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            *_audit_columns(),
            sa.UniqueConstraint("app_id", "username", name="uq_client_user_app_username"),
            comment="客户端最终用户表",
        )
        op.create_index("ix_client_user_app_status", "client_user", ["app_id", "status", "is_deleted"])
        op.create_index("ix_client_user_app_last_active", "client_user", ["app_id", "last_active_at"])
        op.create_index("ix_client_user_created_deleted", "client_user", ["created_time", "is_deleted"])

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("client_user_tag"):
        op.create_table(
            "client_user_tag",
            *_base_columns(),
            sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(32), nullable=False),
            sa.Column("color", sa.String(20), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            *_audit_columns(),
            sa.UniqueConstraint("app_id", "user_id", "name", name="uq_client_user_tag_name"),
            comment="客户端用户人工标签表",
        )
        op.create_index("ix_client_user_tag_app_user", "client_user_tag", ["app_id", "user_id", "is_deleted"])
        op.create_index("ix_client_user_tag_status_deleted", "client_user_tag", ["status", "is_deleted"])
        op.create_index("ix_client_user_tag_created_deleted", "client_user_tag", ["created_time", "is_deleted"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("client_user_tag"):
        op.drop_table("client_user_tag")
    if inspector.has_table("client_user"):
        op.drop_table("client_user")
