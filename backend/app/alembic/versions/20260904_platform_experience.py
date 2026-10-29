"""Add desktop releases, package tiers and provider presentation metadata.

Revision ID: 20260904_platform_experience
Revises: 20260904_user_experience
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_platform_experience"
down_revision: str | None = "20260904_user_experience"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(64), nullable=False, unique=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL"), nullable=True),
    ]


def upgrade() -> None:
    for table in ("pricing_plan_template", "app_catalog_plan"):
        columns = _columns(table)
        if "tier_code" not in columns:
            op.add_column(table, sa.Column("tier_code", sa.String(20), nullable=True))
        if "tier_order" not in columns:
            op.add_column(table, sa.Column("tier_order", sa.Integer(), nullable=False, server_default="0"))

    template_columns = _columns("model_provider_template")
    if "logo_key" not in template_columns:
        op.add_column("model_provider_template", sa.Column("logo_key", sa.String(64), nullable=True))
    if "description" not in template_columns:
        op.add_column("model_provider_template", sa.Column("description", sa.String(500), nullable=True))
    if "recommended_model" not in template_columns:
        op.add_column("model_provider_template", sa.Column("recommended_model", sa.String(128), nullable=True))
    if "adapter_ready" not in template_columns:
        op.add_column("model_provider_template", sa.Column("adapter_ready", sa.Boolean(), nullable=False, server_default=sa.false()))

    tables = _tables()
    if "client_app_release" not in tables:
        op.create_table(
            "client_app_release",
            *_common_columns(),
            sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False),
            sa.Column("platform", sa.String(20), nullable=False, server_default="windows"),
            sa.Column("arch", sa.String(20), nullable=False, server_default="x64"),
            sa.Column("channel", sa.String(20), nullable=False, server_default="test"),
            sa.Column("version", sa.String(32), nullable=False),
            sa.Column("release_notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("min_supported_version", sa.String(32), nullable=True),
            sa.Column("force_update", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("app_id", "channel", "version", name="uq_client_app_release_version"),
        )
        op.create_index("ix_client_app_release_latest", "client_app_release", ["app_id", "platform", "arch", "channel", "status", "published_at"])
        op.create_index("ix_client_app_release_created_deleted", "client_app_release", ["created_time", "is_deleted"])

    if "client_app_release_artifact" not in tables:
        op.create_table(
            "client_app_release_artifact",
            *_common_columns(),
            sa.Column("release_id", sa.Integer(), sa.ForeignKey("client_app_release.id", ondelete="CASCADE"), nullable=False),
            sa.Column("artifact_type", sa.String(20), nullable=False),
            sa.Column("source_type", sa.String(20), nullable=False),
            sa.Column("storage_source_id", sa.Integer(), sa.ForeignKey("storage_source.id", ondelete="SET NULL"), nullable=True),
            sa.Column("storage_path", sa.String(1000), nullable=True),
            sa.Column("external_url", sa.String(2000), nullable=True),
            sa.Column("file_name", sa.String(255), nullable=False),
            sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("sha512", sa.String(172), nullable=True),
            sa.Column("signature_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.UniqueConstraint("release_id", "artifact_type", name="uq_client_app_release_artifact_type"),
        )
        op.create_index("ix_client_app_release_artifact_release", "client_app_release_artifact", ["release_id", "is_deleted"])

    bind = op.get_bind()
    tier_by_code = {"trial": ("free", 0), "starter": ("starter", 10), "professional": ("professional", 20), "enterprise": ("enterprise", 30)}
    for code, (tier_code, tier_order) in tier_by_code.items():
        bind.execute(sa.text("UPDATE pricing_plan_template SET tier_code=:tier, tier_order=:sort WHERE code=:code AND plan_type='subscription'"), {"tier": tier_code, "sort": tier_order, "code": code})
        bind.execute(sa.text("UPDATE app_catalog_plan SET tier_code=:tier, tier_order=:sort WHERE code=:code AND plan_type='subscription'"), {"tier": tier_code, "sort": tier_order, "code": code})

    providers = [
        ("ark", "火山引擎方舟", "https://ark.cn-beijing.volces.com/api/v3", "doubao-seed-1-6", 180),
        ("hunyuan", "腾讯混元", "https://api.hunyuan.cloud.tencent.com/v1", "hunyuan-turbos-latest", 190),
    ]
    for code, name, endpoint, recommended, order in providers:
        bind.execute(
            sa.text("""
            INSERT INTO model_provider_template
                (uuid,is_deleted,created_time,updated_time,code,name,protocol,field_schema,default_endpoint,custom,\"order\",status,logo_key,description,recommended_model,adapter_ready)
            VALUES (CAST(gen_random_uuid() AS VARCHAR),false,NOW(),NOW(),:code,:name,'openai_compatible',
                   CAST(:field_schema AS JSON),
                   :endpoint,false,:sort,'active',:logo_key,:description,:recommended,true)
            ON CONFLICT (code) DO NOTHING
        """),
            {
                "code": code,
                "logo_key": code,
                "name": name,
                "endpoint": endpoint,
                "sort": order,
                "recommended": recommended,
                "description": f"{name} OpenAI 兼容接口",
                "field_schema": json.dumps(
                    [
                        {
                            "key": "api_key",
                            "label": "API Key",
                            "type": "password",
                            "required": True,
                        }
                    ]
                ),
            },
        )


def downgrade() -> None:
    tables = _tables()
    if "client_app_release_artifact" in tables:
        op.drop_table("client_app_release_artifact")
    if "client_app_release" in tables:
        op.drop_table("client_app_release")
    for table in ("app_catalog_plan", "pricing_plan_template"):
        columns = _columns(table)
        if "tier_order" in columns:
            op.drop_column(table, "tier_order")
        if "tier_code" in columns:
            op.drop_column(table, "tier_code")
    for column in ("adapter_ready", "recommended_model", "description", "logo_key"):
        if column in _columns("model_provider_template"):
            op.drop_column("model_provider_template", column)
