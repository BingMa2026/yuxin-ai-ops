from datetime import datetime

from pydantic import BaseModel, Field


class OverviewSummarySchema(BaseModel):
    gross_revenue_yuan: float = 0
    refund_yuan: float = 0
    net_revenue_yuan: float = 0
    # Compatibility alias used by existing clients; now follows the documented
    # net-revenue definition rather than gross paid orders.
    revenue_yuan: float = 0
    provider_cost_yuan: float = 0
    speech_cost_yuan: float = 0
    speech_calls: int = 0
    unknown_cost_calls: int = 0
    supplier_billed_cost_yuan: float = 0
    cost_difference_yuan: float = 0
    reconciliation_coverage_rate: float = 0
    cost_status: str = "estimated"
    direct_margin_yuan: float = 0
    direct_margin_rate: float = 0
    total_users: int = 0
    new_users: int = 0
    active_users: int = 0
    paid_users: int = 0
    active_subscriptions: int = 0
    model_calls: int = 0
    total_tokens: int = 0
    credits_consumed: int = 0
    model_success_rate: float = 0


class OverviewDailySchema(BaseModel):
    date: str
    label: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    gross_revenue_yuan: float = 0
    refund_yuan: float = 0
    net_revenue_yuan: float = 0
    revenue_yuan: float = 0
    provider_cost_yuan: float = 0
    speech_cost_yuan: float = 0
    speech_calls: int = 0
    unknown_cost_calls: int = 0
    supplier_billed_cost_yuan: float = 0
    direct_margin_yuan: float = 0
    new_users: int = 0
    active_users: int = 0
    paid_users: int = 0
    model_calls: int = 0
    total_tokens: int = 0


class OverviewDistributionSchema(BaseModel):
    code: str
    name: str
    count: int = 0
    revenue_yuan: float = 0


class OverviewModelCostSchema(BaseModel):
    model: str
    usage_kind: str = "chat"
    duration_ms: int = 0
    unknown_cost_calls: int = 0
    calls: int = 0
    tokens: int = 0
    cost_yuan: float = 0
    success_rate: float = 0


class OverviewHealthSchema(BaseModel):
    open_tickets: int = 0
    overdue_tickets: int = 0
    expiring_subscriptions: int = 0
    low_credit_users: int = 0
    available_credits: int = 0
    pending_credits: int = 0
    message_delivery_rate: float = 0
    message_read_rate: float = 0
    active_model_routes: int = 0
    provider_finance_accounts: int = 0
    low_balance_accounts: int = 0
    finance_sync_failures: int = 0


class OverviewRiskSchema(BaseModel):
    code: str
    title: str
    description: str
    severity: str
    count: int = 0
    action_path: str | None = None


class OverviewDataQualitySchema(BaseModel):
    telemetry_events: int = 0
    latest_telemetry_at: datetime | None = None
    latest_model_usage_at: datetime | None = None
    latest_supplier_bill_at: datetime | None = None
    actual_usage_calls: int = 0
    estimated_usage_calls: int = 0
    sources: list[str] = Field(default_factory=list)


class OperationsOverviewSchema(BaseModel):
    period_days: int
    period_preset: str
    period_label: str
    grain: str
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    summary: OverviewSummarySchema
    previous: OverviewSummarySchema
    daily: list[OverviewDailySchema] = Field(default_factory=list)
    user_funnel: list[OverviewDistributionSchema] = Field(default_factory=list)
    level_distribution: list[OverviewDistributionSchema] = Field(default_factory=list)
    subscription_distribution: list[OverviewDistributionSchema] = Field(default_factory=list)
    model_cost_distribution: list[OverviewModelCostSchema] = Field(default_factory=list)
    health: OverviewHealthSchema
    risks: list[OverviewRiskSchema] = Field(default_factory=list)
    data_quality: OverviewDataQualitySchema
