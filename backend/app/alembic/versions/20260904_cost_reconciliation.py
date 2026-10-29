"""add model cost ledger, supplier finance ledger and refunds

Revision ID: 20260904_cost_reconciliation
Revises: 20260904_operations_overview
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_cost_reconciliation"
down_revision: str | None = "20260904_operations_overview"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    inspector = _inspector()
    return inspector.has_table(table) and any(item["name"] == column for item in inspector.get_columns(table))


def _add_column(table: str, column: sa.Column) -> None:
    if _inspector().has_table(table) and not _has_column(table, column.name):
        op.add_column(table, column)


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


def _create(name: str, *columns: sa.Column, constraints=(), indexes=(), audit: bool = False, comment: str) -> None:
    if _inspector().has_table(name):
        return
    op.create_table(name, *_base(), *columns, *(_audit() if audit else []), *constraints, comment=comment)
    for index_name, fields in indexes:
        op.create_index(index_name, name, fields)


def upgrade() -> None:
    _create(
        "model_provider_finance_profile",
        sa.Column("provider_account_id", sa.Integer(), sa.ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("adapter_type", sa.String(48), nullable=False),
        sa.Column("settings_cipher", sa.Text(), nullable=False),
        sa.Column("masked_summary", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("balance_warning_yuan", sa.Numeric(18, 4), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="inactive"),
        sa.Column("connection_status", sa.String(20), nullable=False, server_default="untested"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_bill_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        constraints=(sa.UniqueConstraint("provider_account_id", name="uq_model_provider_finance_account"),),
        indexes=(("ix_model_finance_status_sync", ["status", "last_synced_at"]),),
        audit=True,
        comment="模型供应商财务连接（与推理密钥隔离）",
    )
    _create(
        "model_provider_balance_snapshot",
        sa.Column("provider_account_id", sa.Integer(), sa.ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("available_amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("cash_amount", sa.Numeric(20, 8), nullable=True),
        sa.Column("granted_amount", sa.Numeric(20, 8), nullable=True),
        sa.Column("amount_yuan", sa.Numeric(20, 8), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(48), nullable=False),
        sa.Column("raw_summary", sa.JSON(), nullable=False),
        indexes=(("ix_model_balance_account_time", ["provider_account_id", "fetched_at"]),),
        comment="供应商账户余额快照",
    )
    _create(
        "model_provider_bill_item",
        sa.Column("provider_account_id", sa.Integer(), sa.ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(192), nullable=False),
        sa.Column("provider_model_id", sa.String(128), nullable=True),
        sa.Column("billing_type", sa.String(48), nullable=False, server_default="inference"),
        sa.Column("attribution_key", sa.String(128), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("amount_original", sa.Numeric(20, 8), nullable=False),
        sa.Column("amount_yuan", sa.Numeric(20, 8), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(18, 8), nullable=False, server_default="1"),
        sa.Column("usage_detail", sa.JSON(), nullable=False),
        sa.Column("service_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("service_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(48), nullable=False),
        sa.Column("reconciliation_method", sa.String(32), nullable=False, server_default="unmatched"),
        constraints=(sa.UniqueConstraint("provider_account_id", "external_id", name="uq_model_bill_account_external"),),
        indexes=(
            ("ix_model_bill_account_period", ["provider_account_id", "service_start_at"]),
            ("ix_model_bill_model_period", ["provider_model_id", "service_start_at"]),
        ),
        comment="供应商账单明细",
    )
    _create(
        "model_provider_resource_package_snapshot",
        sa.Column("provider_account_id", sa.Integer(), sa.ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(192), nullable=False),
        sa.Column("name", sa.String(192), nullable=False),
        sa.Column("package_type", sa.String(128), nullable=True),
        sa.Column("total_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("remaining_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(48), nullable=False),
        sa.Column("raw_summary", sa.JSON(), nullable=False),
        indexes=(
            ("ix_model_resource_package_account_time", ["provider_account_id", "fetched_at"]),
            ("ix_model_resource_package_expiry", ["provider_account_id", "expires_at"]),
        ),
        comment="供应商资源包余量快照",
    )
    _create(
        "model_provider_sync_task",
        sa.Column("provider_account_id", sa.Integer(), sa.ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sync_type", sa.String(32), nullable=False),
        sa.Column("range_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("range_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("imported_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        indexes=(
            ("ix_model_sync_account_type_time", ["provider_account_id", "sync_type", "created_time"]),
            ("ix_model_sync_status_time", ["status", "created_time"]),
        ),
        comment="供应商财务同步任务",
    )
    _create(
        "model_purchase_price_version",
        sa.Column("provider_account_id", sa.Integer(), sa.ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("catalog_model_id", sa.Integer(), sa.ForeignKey("model_catalog.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_model_id", sa.String(128), nullable=False),
        sa.Column("region", sa.String(64), nullable=True),
        sa.Column("service_tier", sa.String(32), nullable=False, server_default="standard"),
        sa.Column("billing_mode", sa.String(32), nullable=False, server_default="realtime"),
        sa.Column("context_min", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("context_max", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="CNY"),
        sa.Column("exchange_rate_to_cny", sa.Numeric(18, 8), nullable=False, server_default="1"),
        sa.Column("input_cost_per_million", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("cache_read_cost_per_million", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("cache_write_cost_per_million", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("output_cost_per_million", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("reasoning_cost_per_million", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        indexes=(
            ("ix_model_price_catalog_effective", ["catalog_model_id", "effective_from", "status"]),
            ("ix_model_price_account_model", ["provider_account_id", "provider_model_id", "effective_from"]),
        ),
        audit=True,
        comment="版本化模型采购价格",
    )
    _create(
        "model_cost_reconciliation",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_account_id", sa.Integer(), sa.ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_model_id", sa.String(128), nullable=False, server_default="all"),
        sa.Column("billing_type", sa.String(48), nullable=False, server_default="all"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_cost_yuan", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("supplier_cost_yuan", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("difference_yuan", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bill_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reconciliation_method", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="reconciled"),
        indexes=(
            ("ix_model_reconciliation_app_period", ["app_id", "period_start"]),
            ("ix_model_reconciliation_account_period", ["provider_account_id", "period_start"]),
        ),
        comment="请求成本与供应商账单核对结果",
    )
    for _name, column in (
        ("upstream_request_id", sa.Column("upstream_request_id", sa.String(192), nullable=True)),
        ("usage_detail", sa.Column("usage_detail", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json"))),
        ("price_version_id", sa.Column("price_version_id", sa.Integer(), sa.ForeignKey("model_purchase_price_version.id", ondelete="SET NULL"), nullable=True)),
        ("price_snapshot", sa.Column("price_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json"))),
        ("provider_cost_original", sa.Column("provider_cost_original", sa.Numeric(20, 10), nullable=False, server_default="0")),
        ("provider_currency", sa.Column("provider_currency", sa.String(8), nullable=False, server_default="CNY")),
        ("exchange_rate_to_cny", sa.Column("exchange_rate_to_cny", sa.Numeric(18, 8), nullable=False, server_default="1")),
        ("cost_precision", sa.Column("cost_precision", sa.String(24), nullable=False, server_default="estimated_usage")),
        ("reconciliation_status", sa.Column("reconciliation_status", sa.String(24), nullable=False, server_default="unreconciled")),
    ):
        _add_column("model_usage", column)
    if _inspector().has_table("model_usage"):
        op.create_index("ix_model_usage_account_completed", "model_usage", ["provider_account_id", "completed_at"], if_not_exists=True)
        op.execute(sa.text("UPDATE model_usage SET cost_precision = CASE WHEN input_tokens > 0 OR output_tokens > 0 THEN 'actual_usage' ELSE 'estimated_usage' END WHERE cost_precision = 'estimated_usage'"))

    _create(
        "payment_refund",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("payment_order.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("refund_no", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("provider_refund_no", sa.String(128), nullable=True),
        sa.Column("amount_fen", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="CNY"),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="created"),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        constraints=(
            sa.UniqueConstraint("refund_no", name="uq_payment_refund_no"),
            sa.UniqueConstraint("provider", "provider_refund_no", name="uq_payment_refund_provider_no"),
        ),
        indexes=(
            ("ix_payment_refund_app_status_time", ["app_id", "status", "refunded_at"]),
            ("ix_payment_refund_order", ["order_id", "created_time"]),
        ),
        comment="支付退款流水",
    )


def downgrade() -> None:
    for table in (
        "payment_refund",
        "model_cost_reconciliation",
        "model_provider_sync_task",
        "model_provider_resource_package_snapshot",
        "model_provider_bill_item",
        "model_provider_balance_snapshot",
        "model_provider_finance_profile",
    ):
        if _inspector().has_table(table):
            op.drop_table(table)
    if _inspector().has_table("model_usage"):
        for name in (
            "reconciliation_status",
            "cost_precision",
            "exchange_rate_to_cny",
            "provider_currency",
            "provider_cost_original",
            "price_snapshot",
            "price_version_id",
            "usage_detail",
            "upstream_request_id",
        ):
            if _has_column("model_usage", name):
                op.drop_column("model_usage", name)
    if _inspector().has_table("model_purchase_price_version"):
        op.drop_table("model_purchase_price_version")
