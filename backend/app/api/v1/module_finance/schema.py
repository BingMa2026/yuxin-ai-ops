from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.v1.module_payment.channel.schema import PaymentChannelOutSchema

Provider = Literal["alipay", "wechat"]


class FinanceQuery(BaseModel):
    entitlement_kind: Literal["credits", "duration"] | None = None
    mode_switch_status: Literal["pending_payment", "processing", "completed", "requires_confirmation", "failed", "cancelled"] | None = None
    page_no: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    keyword: str = Field(default="", max_length=128)
    provider: Provider | None = None
    status: str | None = Field(default=None, max_length=32)
    purchase_type: str | None = Field(default=None, max_length=24)
    start_date: date | None = None
    end_date: date | None = None
    min_amount_fen: int | None = Field(default=None, ge=0)
    max_amount_fen: int | None = Field(default=None, ge=0)
    user_id: int | None = Field(default=None, gt=0)
    time_field: Literal["created_time", "paid_at"] = "created_time"

    @model_validator(mode="after")
    def valid_range(self):
        if self.start_date and self.end_date and (self.end_date < self.start_date or (self.end_date - self.start_date).days > 366):
            raise ValueError("日期范围必须按先后顺序且不超过367天")
        if self.min_amount_fen is not None and self.max_amount_fen is not None and self.max_amount_fen < self.min_amount_fen:
            raise ValueError("最高金额不能小于最低金额")
        return self


class ReasonIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    reason: str = Field(min_length=2, max_length=500, pattern=r"\S")


class RefundCreate(ReasonIn):
    order_id: int = Field(gt=0)
    amount_fen: int = Field(gt=0, le=10000000000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    entitlement_action: Literal["retain", "terminate"]
    preview_token: str | None = Field(default=None, min_length=64, max_length=64)


class RefundReview(ReasonIn):
    approved: bool
    preview_token: str | None = Field(default=None, min_length=64, max_length=64)


class SubscriptionPreview(BaseModel):
    status: str
    catalog_plan_id: int | None
    plan_name: str
    starts_at: datetime | None
    ends_at: datetime | None


class RefundPreviewOut(BaseModel):
    entitlement_kind: Literal["credits", "duration"] = "credits"
    action: Literal["retain", "terminate"]
    before: SubscriptionPreview
    after: SubscriptionPreview
    revoked_available: int
    cancelled_pending: int
    reserved_at_refund: int
    superseded_credits: int = 0
    consumed_or_expired: int
    cycles_cancelled: int
    preview_token: str


class RefundSync(ReasonIn):
    order_no: str = Field(min_length=1, max_length=128, pattern=r"\S")
    refund_no: str = Field(min_length=1, max_length=128, pattern=r"\S")


class RefundLedgerOut(BaseModel):
    id: int
    order_id: int
    order_no: str
    user_id: int
    username: str
    display_name: str
    provider: str
    provider_refund_no: str | None
    refund_no: str
    amount_fen: int
    refunded_at: datetime | None
    reason: str | None
    status: str


class ControlUpdate(ReasonIn):
    payout_enabled: bool
    refund_enabled: bool
    collection_enabled: bool


class BillCreate(BaseModel):
    provider: Provider
    bill_date: date


class BillBatchCreate(BaseModel):
    provider: Provider
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def valid_range(self):
        if not 0 <= (self.end_date - self.start_date).days < 31:
            raise ValueError("账单日期须按先后顺序选择，单次最多31天")
        return self


class IssueAction(ReasonIn):
    action: Literal["claim", "resolve", "reopen"]


class OrderOut(BaseModel):
    entitlement_kind: Literal["credits", "duration"] = "credits"
    mode_switch: dict | None = None
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_no: str
    user_id: int
    username: str = ""
    display_name: str = ""
    provider: str
    provider_trade_no: str | None
    purchase_type: str
    product_name: str
    amount_fen: int
    refunded_fen: int = 0
    refund_reserved_fen: int = 0
    refundable_fen: int = 0
    status: str
    refund_status: str = "none"
    fulfillment_status: str
    currency: str
    created_time: datetime
    paid_at: datetime | None
    expires_at: datetime
    closed_at: datetime | None
    failure_reason: str | None


class OrderPage(BaseModel):
    items: list[OrderOut]
    total: int
    page_no: int
    page_size: int
    has_next: bool
    total_pages: int
    summary: dict[str, int]


class RecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_time: datetime


class RefundOut(RecordOut):
    order_id: int
    user_id: int
    provider: str
    refund_no: str
    amount_fen: int
    reason: str
    status: str
    entitlement_action: str
    entitlement_result: dict | None
    requested_by: int
    reviewed_by: int | None
    reviewed_at: datetime | None
    review_reason: str | None
    submitted_at: datetime | None
    completed_at: datetime | None
    next_attempt_at: datetime | None
    attempt_count: int
    provider_refund_no: str | None
    failure_code: str | None
    failure_reason: str | None


class RefundListOut(RefundOut):
    order_no: str
    username: str
    display_name: str


class BillOut(RecordOut):
    provider: str
    bill_date: date
    status: str
    requested_by: int
    file_digest: str | None
    downloaded_at: datetime | None
    completed_at: datetime | None
    summary: dict[str, int]
    error_message: str | None


class BillEntryOut(RecordOut):
    bill_id: int
    order_id: int | None
    order_no: str
    provider_trade_no: str | None
    refund_no: str | None
    entry_type: str
    channel_amount_fen: int
    system_amount_fen: int
    fee_fen: int | None
    occurred_at: datetime | None
    match_status: str
    resolution: str | None
    resolved_by: int | None
    resolved_at: datetime | None


class IssueOut(RecordOut):
    kind: str
    severity: str
    object_type: str
    object_id: int
    order_no: str | None
    amount_fen: int | None
    provider: str | None
    status: str
    detail: str
    last_seen_at: datetime
    assigned_to: int | None
    resolution: str | None
    resolved_at: datetime | None


class PageOut[T](BaseModel):
    items: list[T]
    total: int
    page_no: int
    page_size: int
    has_next: bool
    total_pages: int
    summary: dict[str, int] = Field(default_factory=dict)


class OverviewQuery(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_dates(self):
        FinanceQuery(start_date=self.start_date, end_date=self.end_date)
        return self


class MetricsOut(BaseModel):
    received_fen: int
    refund_fen: int
    net_received_fen: int
    payout_fen: int
    paid_orders: int
    average_order_fen: int


class DayMetricsOut(BaseModel):
    date: str
    received_fen: int
    refund_fen: int
    payout_fen: int
    paid_orders: int


class ChannelMetricsOut(BaseModel):
    provider: Provider
    received_fen: int
    paid_orders: int
    refund_fen: int
    created_orders: int
    converted_orders: int
    conversion_rate: float | None


class OverviewOut(BaseModel):
    start_date: date
    end_date: date
    generated_at: datetime
    current: MetricsOut
    previous: MetricsOut
    daily: list[DayMetricsOut]
    channels: list[ChannelMetricsOut]
    tasks: dict[str, int]
    promotion_balances: dict[str, int]
    reconciliation: dict[str, int | None]


class CertificateOut(BaseModel):
    name: str
    expires_at: datetime | None
    days_left: int | None
    status: str


class ChannelOut(PaymentChannelOutSchema):
    payout_enabled: bool
    refund_enabled: bool
    payout_ready: bool
    payout_reason: str
    certificates: list[CertificateOut]
    checked_at: datetime
    last_changed_at: datetime | None


class PayoutOut(BaseModel):
    id: int
    out_bill_no: str
    user_id: int
    provider: str
    amount_fen: int
    status: str
    reason: str | None
    created_time: datetime
    completed_at: datetime | None
    next_attempt_at: datetime | None
    provider_bill_no: str | None
    attempt_count: int
    reviewed_at: datetime | None
    username: str
    display_name: str
    payee: str
