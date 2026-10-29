"""价格体系、刊例、订阅与算力积分。

Revision ID: 20260903_billing_core
Revises: 20260903_client_users
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_billing_core"
down_revision: str | None = "20260903_client_users"
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
        "pricing_standard_version",
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("credit_unit_name", sa.String(32), nullable=False, server_default="算力积分"),
        sa.Column("margin_baseline", sa.Numeric(7, 4), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=True),
        constraints=(sa.UniqueConstraint("version", name="uq_pricing_standard_version"),),
        indexes=(
            ("ix_pricing_standard_version_status_deleted", ["status", "is_deleted"]),
            ("ix_pricing_standard_version_created_deleted", ["created_time", "is_deleted"]),
        ),
        audit=True,
        comment="平台价格体系版本",
    )
    _create(
        "pricing_plan_template",
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("pricing_standard_version.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("billing_period_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("one_time_price_fen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recurring_price_fen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("release_plan", sa.JSON(), nullable=False),
        sa.Column("credit_valid_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("renewal_rule", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("order", sa.Integer(), nullable=False, server_default="999"),
        constraints=(sa.UniqueConstraint("version_id", "code", name="uq_pricing_plan_template_version_code"),),
        indexes=(
            ("ix_pricing_plan_template_version", ["version_id", "status", "is_deleted"]),
            ("ix_pricing_plan_template_created_deleted", ["created_time", "is_deleted"]),
        ),
        audit=True,
        comment="价格体系套餐模板",
    )
    _create(
        "app_catalog_plan",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("pricing_plan_template.id", ondelete="SET NULL"), nullable=True),
        sa.Column("pricing_version_id", sa.Integer(), sa.ForeignKey("pricing_standard_version.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("one_time_price_fen", sa.Integer(), nullable=False),
        sa.Column("recurring_price_fen", sa.Integer(), nullable=False),
        sa.Column("benefit_period_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("total_credits", sa.Integer(), nullable=False),
        sa.Column("release_plan", sa.JSON(), nullable=False),
        sa.Column("credit_valid_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("benefits", sa.JSON(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default="999"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        constraints=(sa.UniqueConstraint("app_id", "code", name="uq_app_catalog_plan_app_code"),),
        indexes=(
            ("ix_app_catalog_plan_app_status", ["app_id", "status", "is_deleted"]),
            ("ix_app_catalog_plan_created_deleted", ["created_time", "is_deleted"]),
        ),
        audit=True,
        comment="客户端应用产品刊例",
    )
    _create(
        "app_pricing_strategy",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("catalog_plan_id", sa.Integer(), sa.ForeignKey("app_catalog_plan.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("purchase_type", sa.String(20), nullable=False, server_default="all"),
        sa.Column("discount_rate", sa.Numeric(7, 4), nullable=True),
        sa.Column("fixed_price_fen", sa.Integer(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="inactive"),
        sa.Column("description", sa.Text(), nullable=True),
        indexes=(
            ("ix_app_pricing_strategy_scope", ["app_id", "catalog_plan_id", "purchase_type", "status"]),
            ("ix_app_pricing_strategy_created_deleted", ["created_time", "is_deleted"]),
        ),
        audit=True,
        comment="客户端应用限时定价策略",
    )
    _create(
        "subscription",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("catalog_plan_id", sa.Integer(), sa.ForeignKey("app_catalog_plan.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_renewal_at", sa.DateTime(timezone=True), nullable=True),
        constraints=(sa.UniqueConstraint("app_id", "user_id", name="uq_subscription_app_user"),),
        indexes=(
            ("ix_subscription_app_status", ["app_id", "status", "is_deleted"]),
            ("ix_subscription_created_deleted", ["created_time", "is_deleted"]),
        ),
        comment="客户端用户订阅",
    )
    _create(
        "subscription_cycle",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("subscription.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("cycle_no", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("plan_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        constraints=(sa.UniqueConstraint("app_id", "subscription_id", "cycle_no", name="uq_subscription_cycle_no"),),
        indexes=(
            ("ix_subscription_cycle_app_status", ["app_id", "status", "is_deleted"]),
            ("ix_subscription_cycle_created_deleted", ["created_time", "is_deleted"]),
        ),
        comment="订阅权益周期",
    )
    _create(
        "credit_account",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("available", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_granted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_consumed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        constraints=(sa.UniqueConstraint("app_id", "user_id", name="uq_credit_account_app_user"),),
        indexes=(
            ("ix_credit_account_app_status", ["app_id", "status", "is_deleted"]),
            ("ix_credit_account_created_deleted", ["created_time", "is_deleted"]),
        ),
        comment="算力积分账户汇总",
    )
    _create(
        "credit_grant",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("release_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("available", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("release_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        constraints=(sa.UniqueConstraint("app_id", "source_type", "source_id", "release_index", name="uq_credit_grant_release"),),
        indexes=(
            ("ix_credit_grant_consume", ["app_id", "user_id", "status", "expires_at"]),
            ("ix_credit_grant_release_due", ["status", "release_at"]),
            ("ix_credit_grant_created_deleted", ["created_time", "is_deleted"]),
        ),
        comment="算力积分批次",
    )
    _create(
        "credit_ledger",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("grant_id", sa.Integer(), sa.ForeignKey("credit_grant.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("reference_type", sa.String(32), nullable=True),
        sa.Column("reference_id", sa.String(128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="posted"),
        constraints=(sa.UniqueConstraint("app_id", "idempotency_key", name="uq_credit_ledger_idempotency"),),
        indexes=(
            ("ix_credit_ledger_app_user", ["app_id", "user_id", "created_time"]),
            ("ix_credit_ledger_status_deleted", ["status", "is_deleted"]),
            ("ix_credit_ledger_created_deleted", ["created_time", "is_deleted"]),
        ),
        comment="不可变算力积分流水",
    )
    _create(
        "credit_reservation",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("estimated", sa.Integer(), nullable=False),
        sa.Column("allocations", sa.JSON(), nullable=False),
        sa.Column("actual", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="reserved"),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        constraints=(sa.UniqueConstraint("app_id", "request_id", name="uq_credit_reservation_request"),),
        indexes=(
            ("ix_credit_reservation_app_status", ["app_id", "status", "is_deleted"]),
            ("ix_credit_reservation_created_deleted", ["created_time", "is_deleted"]),
        ),
        comment="模型调用积分预占",
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in (
        "credit_reservation",
        "credit_ledger",
        "credit_grant",
        "credit_account",
        "subscription_cycle",
        "subscription",
        "app_pricing_strategy",
        "app_catalog_plan",
        "pricing_plan_template",
        "pricing_standard_version",
    ):
        if inspector.has_table(table):
            op.drop_table(table)
