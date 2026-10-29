from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, UserMixin


class ModelProviderTemplateModel(ModelMixin):
    __tablename__ = "model_provider_template"
    __table_args__ = (
        UniqueConstraint("code", name="uq_model_provider_template_code"),
        Index("ix_model_provider_template_status_deleted", "status", "is_deleted"),
        Index("ix_model_provider_template_created_deleted", "created_time", "is_deleted"),
        {"comment": "模型供应商配置模板"},
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False, default="openai_compatible")
    field_schema: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    default_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    logo_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recommended_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    adapter_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    custom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=999)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")


class ModelProviderAccountModel(ModelMixin, UserMixin):
    __tablename__ = "model_provider_account"
    __table_args__ = (
        UniqueConstraint("code", name="uq_model_provider_account_code"),
        Index("ix_model_provider_account_status_deleted", "status", "is_deleted"),
        Index("ix_model_provider_account_created_deleted", "created_time", "is_deleted"),
        {"comment": "平台模型供应商账号"},
    )
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("model_provider_template.id", ondelete="RESTRICT"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    settings_cipher: Mapped[str] = mapped_column(Text, nullable=False)
    masked_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="inactive", server_default="inactive")
    connection_status: Mapped[str] = mapped_column(String(20), nullable=False, default="untested", server_default="untested")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ModelProviderFinanceProfileModel(ModelMixin, UserMixin):
    __tablename__ = "model_provider_finance_profile"
    __table_args__ = (
        UniqueConstraint("provider_account_id", name="uq_model_provider_finance_account"),
        Index("ix_model_finance_status_sync", "status", "last_synced_at"),
        Index("ix_model_finance_created_deleted", "created_time", "is_deleted"),
        {"comment": "模型供应商财务连接（与推理密钥隔离）"},
    )
    provider_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False
    )
    adapter_type: Mapped[str] = mapped_column(String(48), nullable=False)
    settings_cipher: Mapped[str] = mapped_column(Text, nullable=False)
    masked_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    capabilities: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    balance_warning_yuan: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="inactive", server_default="inactive")
    connection_status: Mapped[str] = mapped_column(String(20), nullable=False, default="untested", server_default="untested")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_bill_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ModelProviderBalanceSnapshotModel(ModelMixin):
    __tablename__ = "model_provider_balance_snapshot"
    __table_args__ = (
        Index("ix_model_balance_account_time", "provider_account_id", "fetched_at"),
        Index("ix_model_balance_created_deleted", "created_time", "is_deleted"),
        {"comment": "供应商账户余额快照"},
    )
    provider_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    available_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    granted_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    amount_yuan: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(48), nullable=False)
    raw_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ModelProviderResourcePackageSnapshotModel(ModelMixin):
    __tablename__ = "model_provider_resource_package_snapshot"
    __table_args__ = (
        Index("ix_model_resource_package_account_time", "provider_account_id", "fetched_at"),
        Index("ix_model_resource_package_expiry", "provider_account_id", "expires_at"),
        Index("ix_model_resource_package_created_deleted", "created_time", "is_deleted"),
        {"comment": "供应商资源包余量快照"},
    )
    provider_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(192), nullable=False)
    name: Mapped[str] = mapped_column(String(192), nullable=False)
    package_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    remaining_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(48), nullable=False)
    raw_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ModelProviderBillItemModel(ModelMixin):
    __tablename__ = "model_provider_bill_item"
    __table_args__ = (
        UniqueConstraint("provider_account_id", "external_id", name="uq_model_bill_account_external"),
        Index("ix_model_bill_account_period", "provider_account_id", "service_start_at"),
        Index("ix_model_bill_model_period", "provider_model_id", "service_start_at"),
        Index("ix_model_bill_created_deleted", "created_time", "is_deleted"),
        {"comment": "供应商账单明细"},
    )
    provider_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(192), nullable=False)
    provider_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    billing_type: Mapped[str] = mapped_column(String(48), nullable=False, default="inference")
    attribution_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    amount_original: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    amount_yuan: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=1, server_default="1")
    usage_detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    service_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    service_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(48), nullable=False)
    reconciliation_method: Mapped[str] = mapped_column(String(32), nullable=False, default="unmatched", server_default="unmatched")


class ModelProviderSyncTaskModel(ModelMixin):
    __tablename__ = "model_provider_sync_task"
    __table_args__ = (
        Index("ix_model_sync_account_type_time", "provider_account_id", "sync_type", "created_time"),
        Index("ix_model_sync_status_time", "status", "created_time"),
        {"comment": "供应商财务同步任务"},
    )
    provider_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False
    )
    sync_type: Mapped[str] = mapped_column(String(32), nullable=False)
    range_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    range_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", server_default="running")
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelCostReconciliationModel(ModelMixin):
    __tablename__ = "model_cost_reconciliation"
    __table_args__ = (
        Index("ix_model_reconciliation_app_period", "app_id", "period_start"),
        Index("ix_model_reconciliation_account_period", "provider_account_id", "period_start"),
        Index("ix_model_reconciliation_created_deleted", "created_time", "is_deleted"),
        {"comment": "请求成本与供应商账单核对结果"},
    )
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False)
    provider_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False
    )
    provider_model_id: Mapped[str] = mapped_column(String(128), nullable=False, default="all", server_default="all")
    billing_type: Mapped[str] = mapped_column(String(48), nullable=False, default="all", server_default="all")
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_cost_yuan: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0, server_default="0")
    supplier_cost_yuan: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0, server_default="0")
    difference_yuan: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0, server_default="0")
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    bill_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reconciliation_method: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="reconciled", server_default="reconciled")


class ModelCatalogModel(ModelMixin, UserMixin):
    __tablename__ = "model_catalog"
    __table_args__ = (
        UniqueConstraint("provider_account_id", "provider_model_id", name="uq_model_catalog_provider_model"),
        Index("ix_model_catalog_provider_status", "provider_account_id", "status", "is_deleted"),
        Index("ix_model_catalog_created_deleted", "created_time", "is_deleted"),
        {"comment": "平台模型目录"},
    )
    provider_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("model_provider_account.id", ondelete="RESTRICT"), nullable=False)
    provider_model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    context_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speech_protocol: Mapped[str | None] = mapped_column(String(40), nullable=True)
    speech_pricing: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    supports_stream: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    supports_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    supports_vision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    supports_pdf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    input_cost_per_million: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False, default=0)
    output_cost_per_million: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False, default=0)
    input_credits_per_1k: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_credits_per_1k: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    minimum_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="inactive", server_default="inactive")


class ModelPurchasePriceVersionModel(ModelMixin, UserMixin):
    __tablename__ = "model_purchase_price_version"
    __table_args__ = (
        Index("ix_model_price_catalog_effective", "catalog_model_id", "effective_from", "status"),
        Index("ix_model_price_account_model", "provider_account_id", "provider_model_id", "effective_from"),
        Index("ix_model_price_created_deleted", "created_time", "is_deleted"),
        {"comment": "版本化模型采购价格"},
    )
    provider_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("model_provider_account.id", ondelete="CASCADE"), nullable=False
    )
    catalog_model_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("model_catalog.id", ondelete="CASCADE"), nullable=False
    )
    provider_model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="standard", server_default="standard")
    billing_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="realtime", server_default="realtime")
    context_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    context_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY", server_default="CNY")
    exchange_rate_to_cny: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=1, server_default="1")
    input_cost_per_million: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=0, server_default="0")
    cache_read_cost_per_million: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=0, server_default="0")
    cache_write_cost_per_million: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=0, server_default="0")
    output_cost_per_million: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=0, server_default="0")
    reasoning_cost_per_million: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=0, server_default="0")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", server_default="manual")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")


class AppModelBindingModel(ModelMixin, UserMixin):
    __tablename__ = "app_model_binding"
    __table_args__ = (
        UniqueConstraint("app_id", "catalog_model_id", name="uq_app_model_binding_model"),
        UniqueConstraint("app_id", "public_model_code", name="uq_app_model_binding_public_code"),
        Index("ix_app_model_binding_app_status", "app_id", "status", "is_deleted"),
        Index("ix_app_model_binding_created_deleted", "created_time", "is_deleted"),
        {"comment": "客户端应用模型授权"},
    )
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    catalog_model_id: Mapped[int] = mapped_column(Integer, ForeignKey("model_catalog.id", ondelete="RESTRICT"), nullable=False)
    public_model_code: Mapped[str] = mapped_column(String(64), nullable=False)
    client_display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    user_selectable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    input_credits_per_1k: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_credits_per_1k: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fallback_binding_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("app_model_binding.id", ondelete="SET NULL"), nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=999)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="inactive", server_default="inactive")


class AppModelRouteModel(ModelMixin, UserMixin):
    __tablename__ = "app_model_route"
    __table_args__ = (
        UniqueConstraint("app_id", "business_code", name="uq_app_model_route_business"),
        Index("ix_app_model_route_app_status", "app_id", "status", "is_deleted"),
        Index("ix_app_model_route_created_deleted", "created_time", "is_deleted"),
        {"comment": "客户端应用业务模型路由"},
    )
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    business_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_binding_id: Mapped[int] = mapped_column(Integer, ForeignKey("app_model_binding.id", ondelete="RESTRICT"), nullable=False)
    fallback_binding_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    allow_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    allow_user_model: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="inactive", server_default="inactive")


class ModelUsageModel(ModelMixin):
    __tablename__ = "model_usage"
    __table_args__ = (
        UniqueConstraint("app_id", "request_id", name="uq_model_usage_request"),
        Index("ix_model_usage_app_user", "app_id", "user_id", "created_time"),
        Index("ix_model_usage_app_status", "app_id", "status", "is_deleted"),
        Index("ix_model_usage_created_deleted", "created_time", "is_deleted"),
        {"comment": "模型调用用量（不保存提示词和响应正文）"},
    )
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    business_code: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("app_model_binding.id", ondelete="SET NULL"), nullable=True)
    provider_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("model_provider_account.id", ondelete="SET NULL"), nullable=True)
    provider_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    upstream_request_id: Mapped[str | None] = mapped_column(String(192), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usage_detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    price_version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("model_purchase_price_version.id", ondelete="SET NULL"), nullable=True
    )
    price_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    provider_cost_original: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False, default=0, server_default="0")
    provider_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY", server_default="CNY")
    exchange_rate_to_cny: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=1, server_default="1")
    charged_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_cost_yuan: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=0, server_default="0")
    cost_precision: Mapped[str] = mapped_column(String(24), nullable=False, default="estimated_usage", server_default="estimated_usage")
    reconciliation_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unreconciled", server_default="unreconciled")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", server_default="running")
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
