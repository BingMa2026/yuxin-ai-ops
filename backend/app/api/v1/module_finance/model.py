"""Finance workflow records. PaymentOrder/PaymentRefund remain the payment ledger."""

from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin


class FinanceControlModel(ModelMixin):
    __tablename__ = "finance_channel_control"
    __table_args__ = (UniqueConstraint("app_id", "provider", name="uq_finance_control_scope"),)
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    payout_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    refund_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(500))


class FinanceAuditModel(ModelMixin):
    __tablename__ = "finance_audit"
    __table_args__ = (Index("ix_finance_audit_object", "app_id", "object_type", "object_id", "created_time"),)
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    operator_id: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    before: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    after: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class FinanceRefundRequestModel(ModelMixin):
    __tablename__ = "finance_refund_request"
    __table_args__ = (
        UniqueConstraint("refund_no", name="uq_finance_refund_no"),
        UniqueConstraint("app_id", "idempotency_key", name="uq_finance_refund_idempotency"),
        CheckConstraint("amount_fen > 0", name="ck_finance_refund_positive"),
        Index("ix_finance_refund_queue", "status", "next_attempt_at"),
        Index("ix_finance_refund_order", "app_id", "order_id", "status"),
    )
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("payment_order.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    refund_no: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="review", nullable=False)
    entitlement_action: Mapped[str] = mapped_column(String(24), nullable=False)
    entitlement_result: Mapped[dict | None] = mapped_column(JSON)
    merchant_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_by: Mapped[int] = mapped_column(Integer, nullable=False)
    reviewed_by: Mapped[int | None] = mapped_column(Integer)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(String(500))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_refund_no: Mapped[str | None] = mapped_column(String(128))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    failure_reason: Mapped[str | None] = mapped_column(String(500))


class FinanceBillModel(ModelMixin):
    __tablename__ = "finance_bill"
    __table_args__ = (UniqueConstraint("app_id", "provider", "bill_date", name="uq_finance_bill_scope_date"),)
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    bill_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False)
    merchant_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_by: Mapped[int] = mapped_column(Integer, nullable=False)
    file_digest: Mapped[str | None] = mapped_column(String(128))
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(500))


class FinanceBillEntryModel(ModelMixin):
    __tablename__ = "finance_bill_entry"
    __table_args__ = (
        UniqueConstraint("bill_id", "entry_key", name="uq_finance_bill_entry_key"),
        Index("ix_finance_bill_entry_status", "app_id", "bill_id", "match_status"),
    )
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    bill_id: Mapped[int] = mapped_column(ForeignKey("finance_bill.id"), nullable=False)
    entry_key: Mapped[str] = mapped_column(String(128), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("payment_order.id"))
    order_no: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_trade_no: Mapped[str | None] = mapped_column(String(128))
    refund_no: Mapped[str | None] = mapped_column(String(128))
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False)
    channel_amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    system_amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_fen: Mapped[int | None] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    match_status: Mapped[str] = mapped_column(String(32), nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(1000))
    resolved_by: Mapped[int | None] = mapped_column(Integer)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FinanceIssueModel(ModelMixin):
    __tablename__ = "finance_issue"
    __table_args__ = (UniqueConstraint("app_id", "issue_key", name="uq_finance_issue_key"), Index("ix_finance_issue_status", "app_id", "status", "last_seen_at"))
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    issue_key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[int] = mapped_column(Integer, nullable=False)
    order_no: Mapped[str | None] = mapped_column(String(128))
    amount_fen: Mapped[int | None] = mapped_column(BigInteger)
    provider: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assigned_to: Mapped[int | None] = mapped_column(Integer)
    resolution: Mapped[str | None] = mapped_column(String(1000))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
