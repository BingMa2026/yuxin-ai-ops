from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import ModelMixin, UserMixin


class PricingStandardVersionModel(ModelMixin, UserMixin):
    __tablename__ = "pricing_standard_version"
    __table_args__ = (
        UniqueConstraint("version", name="uq_pricing_standard_version"),
        Index("ix_pricing_standard_version_status_deleted", "status", "is_deleted"),
        Index("ix_pricing_standard_version_created_deleted", "created_time", "is_deleted"),
        {"comment": "平台价格体系版本"},
    )

    version: Mapped[str] = mapped_column(String(32), nullable=False, comment="版本号")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="版本名称")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft", comment="draft/published/archived")
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    credit_unit_name: Mapped[str] = mapped_column(String(32), nullable=False, default="算力积分", server_default="算力积分")
    margin_baseline: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False, default=60, server_default="60")
    credits_per_yuan: Mapped[int] = mapped_column(Integer, nullable=False, default=1000, server_default="1000")
    subscription_cycle_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    renewal_discount_rate: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False, default=0.9, server_default="0.9")
    margin_floor: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False, default=25, server_default="25")
    account_priority: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class PricingPlanTemplateModel(ModelMixin, UserMixin):
    entitlement_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="credits", server_default="credits")

    __tablename__ = "pricing_plan_template"
    __table_args__ = (
        UniqueConstraint("version_id", "code", name="uq_pricing_plan_template_version_code"),
        Index("ix_pricing_plan_template_version", "version_id", "status", "is_deleted"),
        Index("ix_pricing_plan_template_created_deleted", "created_time", "is_deleted"),
        {"comment": "价格体系套餐模板"},
    )

    version_id: Mapped[int] = mapped_column(Integer, ForeignKey("pricing_standard_version.id", ondelete="RESTRICT"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_type: Mapped[str] = mapped_column(String(20), nullable=False, default="subscription", server_default="subscription")
    tier_code: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="free/starter/professional/enterprise")
    tier_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    billing_period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    one_time_price_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    recurring_price_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    release_plan: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    credit_valid_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    renewal_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    benefits: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    requires_active_subscription: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=999, server_default="999")


class AppCatalogPlanModel(ModelMixin, UserMixin):
    entitlement_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="credits", server_default="credits")

    __tablename__ = "app_catalog_plan"
    __table_args__ = (
        Index("uq_app_catalog_plan_app_code", "app_id", "code", unique=True, postgresql_where=text("is_deleted = false"), sqlite_where=text("is_deleted = 0")),
        Index("ix_app_catalog_plan_app_status", "app_id", "status", "is_deleted"),
        Index("ix_app_catalog_plan_created_deleted", "created_time", "is_deleted"),
        {"comment": "客户端应用产品刊例"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    template_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("pricing_plan_template.id", ondelete="SET NULL"), nullable=True)
    pricing_version_id: Mapped[int] = mapped_column(Integer, ForeignKey("pricing_standard_version.id", ondelete="RESTRICT"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_type: Mapped[str] = mapped_column(String(20), nullable=False, default="subscription", server_default="subscription")
    tier_code: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="free/starter/professional/enterprise")
    tier_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    one_time_price_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    recurring_price_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    benefit_period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    total_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    release_plan: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    credit_valid_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    benefits: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    requires_active_subscription: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    cost_budget_yuan: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=999, server_default="999")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft", comment="draft/on_sale/off_sale")


class AppPricingStrategyModel(ModelMixin, UserMixin):
    __tablename__ = "app_pricing_strategy"
    __table_args__ = (
        Index("ix_app_pricing_strategy_scope", "app_id", "catalog_plan_id", "purchase_type", "status"),
        Index("ix_app_pricing_strategy_created_deleted", "created_time", "is_deleted"),
        {"comment": "客户端应用限时定价策略"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pricing_version_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("pricing_standard_version.id", ondelete="RESTRICT"), nullable=True)
    catalog_plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("app_catalog_plan.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    purchase_type: Mapped[str] = mapped_column(String(20), nullable=False, default="all", server_default="all")
    discount_rate: Mapped[float | None] = mapped_column(Numeric(7, 4), nullable=True)
    fixed_price_fen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="inactive", server_default="inactive")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="all", server_default="all")
    scope_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["AppPricingStrategyItemModel"]] = relationship(back_populates="strategy", cascade="all, delete-orphan")


class AppPricingStrategyItemModel(ModelMixin, UserMixin):
    __tablename__ = "app_pricing_strategy_item"
    __table_args__ = (
        UniqueConstraint("strategy_id", "catalog_plan_id", "purchase_type", name="uq_strategy_item_plan_purchase"),
        Index("ix_strategy_item_app_strategy", "app_id", "strategy_id", "is_deleted"),
        {"comment": "定价策略刊例项"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("app_pricing_strategy.id", ondelete="CASCADE"), nullable=False)
    catalog_plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("app_catalog_plan.id", ondelete="RESTRICT"), nullable=False)
    purchase_type: Mapped[str] = mapped_column(String(20), nullable=False, default="all", server_default="all")
    discount_rate: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False, default=1, server_default="1")
    execution_price_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    margin_rate: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    allowed_cost_yuan: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    credits_per_cost_yuan: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True)

    strategy: Mapped[AppPricingStrategyModel] = relationship(back_populates="items")


class SubscriptionModel(ModelMixin):
    entitlement_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="credits", server_default="credits")

    __tablename__ = "subscription"
    __table_args__ = (
        UniqueConstraint("app_id", "user_id", name="uq_subscription_app_user"),
        Index("ix_subscription_app_status", "app_id", "status", "is_deleted"),
        Index("ix_subscription_created_deleted", "created_time", "is_deleted"),
        {"comment": "客户端用户订阅"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False)
    catalog_plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("app_catalog_plan.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_renewal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SubscriptionCycleModel(ModelMixin):
    __tablename__ = "subscription_cycle"
    __table_args__ = (
        UniqueConstraint("app_id", "subscription_id", "cycle_no", name="uq_subscription_cycle_no"),
        Index("ix_subscription_cycle_app_status", "app_id", "status", "is_deleted"),
        Index("ix_subscription_cycle_created_deleted", "created_time", "is_deleted"),
        {"comment": "订阅权益周期"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    subscription_id: Mapped[int] = mapped_column(Integer, ForeignKey("subscription.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cycle_no: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    plan_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")


class DurationAdjustmentModel(ModelMixin, UserMixin):
    __tablename__ = "duration_adjustment"
    __table_args__ = (
        UniqueConstraint("app_id", "idempotency_key", name="uq_duration_adjustment_request"),
        Index("ix_duration_adjustment_user", "app_id", "user_id", "created_time"),
    )

    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscription.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    seconds_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    before_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    after_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    operator_name: Mapped[str] = mapped_column(String(150), nullable=False)
    cycle_changes: Mapped[list] = mapped_column(JSON, nullable=False)


class CreditAccountModel(ModelMixin):
    __tablename__ = "credit_account"
    __table_args__ = (
        UniqueConstraint("app_id", "user_id", name="uq_credit_account_app_user"),
        Index("ix_credit_account_app_status", "app_id", "status", "is_deleted"),
        Index("ix_credit_account_created_deleted", "created_time", "is_deleted"),
        {"comment": "算力积分账户汇总"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False)
    available: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_granted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_consumed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")


class CreditGrantModel(ModelMixin):
    __tablename__ = "credit_grant"
    __table_args__ = (
        UniqueConstraint("app_id", "source_type", "source_id", "release_index", name="uq_credit_grant_release"),
        Index("ix_credit_grant_consume", "app_id", "user_id", "status", "expires_at"),
        Index("ix_credit_grant_release_due", "status", "release_at"),
        Index("ix_credit_grant_created_deleted", "created_time", "is_deleted"),
        {"comment": "算力积分批次"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False, default="monthly_reserve", server_default="monthly_reserve")
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    release_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    available: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    release_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    credits_per_cost_yuan: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False, default=2500, server_default="2500")
    pricing_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class CreditLedgerModel(ModelMixin):
    __tablename__ = "credit_ledger"
    __table_args__ = (
        UniqueConstraint("app_id", "idempotency_key", name="uq_credit_ledger_idempotency"),
        Index("ix_credit_ledger_app_user", "app_id", "user_id", "created_time"),
        Index("ix_credit_ledger_status_deleted", "status", "is_deleted"),
        Index("ix_credit_ledger_created_deleted", "created_time", "is_deleted"),
        {"comment": "不可变算力积分流水"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False)
    grant_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("credit_grant.id", ondelete="RESTRICT"), nullable=True)
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sys_user.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="posted", server_default="posted")


class CreditReservationModel(ModelMixin):
    __tablename__ = "credit_reservation"
    __table_args__ = (
        UniqueConstraint("app_id", "request_id", name="uq_credit_reservation_request"),
        Index("ix_credit_reservation_app_status", "app_id", "status", "is_deleted"),
        Index("ix_credit_reservation_created_deleted", "created_time", "is_deleted"),
        {"comment": "模型调用积分预占"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    estimated: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_yuan: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    allocations: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    actual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_cost_yuan: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="reserved", server_default="reserved")
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
