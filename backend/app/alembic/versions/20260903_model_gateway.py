"""模型供应商、目录、客户端授权、路由与用量。

Revision ID: 20260903_model_gateway
Revises: 20260903_billing_core
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_model_gateway"
down_revision: str | None = "20260903_billing_core"
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


def _audit() -> list[sa.Column]:
    return [
        sa.Column("created_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True),
        sa.Column("updated_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True),
        sa.Column("deleted_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True),
    ]


def _create(name: str, *columns, constraints=(), indexes=(), audit: bool = False, comment: str) -> None:
    if sa.inspect(op.get_bind()).has_table(name):
        return
    op.create_table(name, *_base(), *columns, *(_audit() if audit else []), *constraints, comment=comment)
    for index_name, fields in indexes:
        op.create_index(index_name, name, fields)


def upgrade() -> None:
    _create(
        "model_provider_template",
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False, server_default="openai_compatible"),
        sa.Column("field_schema", sa.JSON(), nullable=False),
        sa.Column("default_endpoint", sa.String(500), nullable=True),
        sa.Column("custom", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("order", sa.Integer(), nullable=False, server_default="999"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        constraints=(sa.UniqueConstraint("code", name="uq_model_provider_template_code"),),
        indexes=(
            ("ix_model_provider_template_status_deleted", ["status", "is_deleted"]),
            ("ix_model_provider_template_created_deleted", ["created_time", "is_deleted"]),
        ),
        comment="模型供应商配置模板",
    )
    _create(
        "model_provider_account",
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("model_provider_template.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("endpoint", sa.String(500), nullable=False),
        sa.Column("settings_cipher", sa.Text(), nullable=False),
        sa.Column("masked_summary", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="inactive"),
        sa.Column("connection_status", sa.String(20), nullable=False, server_default="untested"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        constraints=(sa.UniqueConstraint("code", name="uq_model_provider_account_code"),),
        indexes=(
            ("ix_model_provider_account_status_deleted", ["status", "is_deleted"]),
            ("ix_model_provider_account_created_deleted", ["created_time", "is_deleted"]),
        ),
        audit=True,
        comment="平台模型供应商账号",
    )
    _create(
        "model_catalog",
        sa.Column("provider_account_id", sa.Integer(), sa.ForeignKey("model_provider_account.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider_model_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("context_length", sa.Integer(), nullable=True),
        sa.Column("supports_stream", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("supports_tools", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supports_vision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supports_pdf", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("input_cost_per_million", sa.Numeric(14, 6), nullable=False, server_default="0"),
        sa.Column("output_cost_per_million", sa.Numeric(14, 6), nullable=False, server_default="0"),
        sa.Column("input_credits_per_1k", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_credits_per_1k", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("minimum_credits", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="inactive"),
        constraints=(sa.UniqueConstraint("provider_account_id", "provider_model_id", name="uq_model_catalog_provider_model"),),
        indexes=(
            ("ix_model_catalog_provider_status", ["provider_account_id", "status", "is_deleted"]),
            ("ix_model_catalog_created_deleted", ["created_time", "is_deleted"]),
        ),
        audit=True,
        comment="平台模型目录",
    )
    _create(
        "app_model_binding",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("catalog_model_id", sa.Integer(), sa.ForeignKey("model_catalog.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("public_model_code", sa.String(64), nullable=False),
        sa.Column("client_display_name", sa.String(128), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("user_selectable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("input_credits_per_1k", sa.Integer(), nullable=True),
        sa.Column("output_credits_per_1k", sa.Integer(), nullable=True),
        sa.Column("fallback_binding_id", sa.Integer(), sa.ForeignKey("app_model_binding.id", ondelete="SET NULL"), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default="999"),
        sa.Column("status", sa.String(20), nullable=False, server_default="inactive"),
        constraints=(
            sa.UniqueConstraint("app_id", "catalog_model_id", name="uq_app_model_binding_model"),
            sa.UniqueConstraint("app_id", "public_model_code", name="uq_app_model_binding_public_code"),
        ),
        indexes=(
            ("ix_app_model_binding_app_status", ["app_id", "status", "is_deleted"]),
            ("ix_app_model_binding_created_deleted", ["created_time", "is_deleted"]),
        ),
        audit=True,
        comment="客户端应用模型授权",
    )
    _create(
        "app_model_route",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("business_code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("primary_binding_id", sa.Integer(), sa.ForeignKey("app_model_binding.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("fallback_binding_ids", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("allow_tools", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_user_model", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(20), nullable=False, server_default="inactive"),
        constraints=(sa.UniqueConstraint("app_id", "business_code", name="uq_app_model_route_business"),),
        indexes=(
            ("ix_app_model_route_app_status", ["app_id", "status", "is_deleted"]),
            ("ix_app_model_route_created_deleted", ["created_time", "is_deleted"]),
        ),
        audit=True,
        comment="客户端应用业务模型路由",
    )
    _create(
        "model_usage",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("business_code", sa.String(64), nullable=False),
        sa.Column("binding_id", sa.Integer(), sa.ForeignKey("app_model_binding.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider_account_id", sa.Integer(), sa.ForeignKey("model_provider_account.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider_model_id", sa.String(128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("charged_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_cost_yuan", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_token_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("error_category", sa.String(64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        constraints=(sa.UniqueConstraint("app_id", "request_id", name="uq_model_usage_request"),),
        indexes=(
            ("ix_model_usage_app_user", ["app_id", "user_id", "created_time"]),
            ("ix_model_usage_app_status", ["app_id", "status", "is_deleted"]),
            ("ix_model_usage_created_deleted", ["created_time", "is_deleted"]),
        ),
        comment="模型调用用量（不保存提示词和响应正文）",
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in (
        "model_usage",
        "app_model_route",
        "app_model_binding",
        "model_catalog",
        "model_provider_account",
        "model_provider_template",
    ):
        if inspector.has_table(table):
            op.drop_table(table)
