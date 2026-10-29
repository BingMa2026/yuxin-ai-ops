from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin


class PaymentOrderModel(ModelMixin):
    __tablename__ = "payment_order"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_payment_order_no"),
        UniqueConstraint("app_id", "user_id", "idempotency_key", name="uq_payment_order_idempotency"),
        UniqueConstraint("provider", "provider_trade_no", name="uq_payment_order_provider_trade"),
        Index("ix_payment_order_app_status", "app_id", "status", "created_time"),
        Index("ix_payment_order_recovery", "app_id", "status", "next_query_at"),
        Index("ix_payment_order_app_user", "app_id", "user_id", "created_time"),
        Index("ix_payment_order_created_deleted", "created_time", "is_deleted"),
        {"comment": "客户端支付订单"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    catalog_plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("app_catalog_plan.id", ondelete="RESTRICT"), nullable=False)
    purchase_type: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY", server_default="CNY")
    plan_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    strategy_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created", server_default="created")
    mode_switch: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="模式切换确认及处理结果；支付状态独立")
    pay_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_trade_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    next_query_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    query_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="关闭请求时间，渠道结果未明时继续重试")
    replaces_order_no: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="本次购买替换的原支付订单")
    replaced_by_order_no: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="替换本订单的新支付订单，原单仍核验收款")
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    auto_renew_requested: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="0")


class PaymentCallbackModel(ModelMixin):
    __tablename__ = "payment_callback"
    __table_args__ = (
        UniqueConstraint("provider", "callback_id", name="uq_payment_callback_provider_id"),
        Index("ix_payment_callback_order", "order_no", "status"),
        Index("ix_payment_callback_created_deleted", "created_time", "is_deleted"),
        {"comment": "支付回调去重与审计（不保存密钥）"},
    )

    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    callback_id: Mapped[str] = mapped_column(String(128), nullable=False)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_trade_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount_fen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received", server_default="received")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class PaymentAttemptModel(ModelMixin):
    __tablename__ = "payment_attempt"
    __table_args__ = (
        Index("ix_payment_attempt_app_order", "app_id", "order_id", "created_time"),
        Index("ix_payment_attempt_provider_status", "provider", "status", "created_time"),
        Index("ix_payment_attempt_created_deleted", "created_time", "is_deleted"),
        {"comment": "支付渠道下单与主动查单尝试"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("payment_order.id", ondelete="RESTRICT"), nullable=False)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentRefundModel(ModelMixin):
    __tablename__ = "payment_refund"
    __table_args__ = (
        UniqueConstraint("refund_no", name="uq_payment_refund_no"),
        UniqueConstraint("provider", "provider_refund_no", name="uq_payment_refund_provider_no"),
        Index("ix_payment_refund_app_status_time", "app_id", "status", "refunded_at"),
        Index("ix_payment_refund_order", "order_id", "created_time"),
        Index("ix_payment_refund_created_deleted", "created_time", "is_deleted"),
        {"comment": "支付退款流水"},
    )
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("payment_order.id", ondelete="RESTRICT"), nullable=False)
    refund_no: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_refund_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY", server_default="CNY")
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created", server_default="created")
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
