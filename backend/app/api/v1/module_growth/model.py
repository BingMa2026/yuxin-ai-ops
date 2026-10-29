"""Client-scoped policy versions, referral facts and immutable reward accounting."""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin


class GrowthPolicyModel(ModelMixin):
    __tablename__ = "growth_policy"
    __table_args__ = (UniqueConstraint("app_id", "key", "version", name="uq_growth_policy_version"), Index("ix_growth_policy_current", "app_id", "kind", "status", "effective_at"))
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"))
    used_credits: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    used_cash_fen: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class GrowthProfileModel(ModelMixin):
    __tablename__ = "growth_profile"
    __table_args__ = (UniqueConstraint("app_id", "user_id", name="uq_growth_profile_user"), UniqueConstraint("invite_code", name="uq_growth_invite_code"))
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(24), nullable=False)
    usage_grade: Mapped[str] = mapped_column(String(8), default="R1", nullable=False)
    promotion_grade: Mapped[str] = mapped_column(String(8), default="ungraded", nullable=False)
    first_task_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evaluations: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    credit_debt: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class ReferralModel(ModelMixin):
    __tablename__ = "growth_referral"
    __table_args__ = (
        UniqueConstraint("app_id", "invitee_id", name="uq_growth_referral_invitee"),
        CheckConstraint("inviter_id != invitee_id", name="ck_growth_referral_not_self"),
        Index("ix_growth_referral_inviter", "app_id", "inviter_id", "bound_at"),
    )
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    inviter_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    invitee_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    risk_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    risk_reason: Mapped[str | None] = mapped_column(String(500))


class GradeEvaluationModel(ModelMixin):
    __tablename__ = "growth_grade_evaluation"
    __table_args__ = (UniqueConstraint("app_id", "user_id", "track", "period_key", "policy_id", name="uq_growth_grade_period"), Index("ix_growth_grade_user", "app_id", "user_id", "track"))
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    policy_id: Mapped[int] = mapped_column(ForeignKey("growth_policy.id"), nullable=False)
    track: Mapped[str] = mapped_column(String(16), nullable=False)
    period_key: Mapped[str] = mapped_column(String(32), nullable=False)
    old_grade: Mapped[str] = mapped_column(String(8), nullable=False)
    new_grade: Mapped[str] = mapped_column(String(8), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)


class GrowthTaskModel(ModelMixin):
    __tablename__ = "growth_task"
    __table_args__ = (UniqueConstraint("app_id", "user_id", "local_task_id", name="uq_growth_task_local"), Index("ix_growth_task_user", "app_id", "user_id", "status"))
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    local_task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    project_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="started", nullable=False)
    artifact_ref: Mapped[str | None] = mapped_column(String(128))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(String(500))


class GrowthEventModel(ModelMixin):
    __tablename__ = "growth_event"
    __table_args__ = (UniqueConstraint("app_id", "event_key", name="uq_growth_event_key"), Index("ix_growth_event_pending", "status", "created_time"))
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    event_key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    facts: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))


class TaskEvidenceModel(ModelMixin):
    __tablename__ = "growth_task_evidence"
    __table_args__ = (UniqueConstraint("app_id", "request_id", name="uq_growth_evidence_request"),)
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    task_id: Mapped[int] = mapped_column(ForeignKey("growth_task.id"), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    business_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)


class RewardModel(ModelMixin):
    __tablename__ = "growth_reward"
    __table_args__ = (
        UniqueConstraint("app_id", "entitlement_key", "user_id", "asset", name="uq_growth_reward_once"),
        CheckConstraint("amount >= 0", name="ck_growth_reward_amount"),
        Index("ix_growth_reward_due", "status", "release_at"),
    )
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    event_id: Mapped[int] = mapped_column(ForeignKey("growth_event.id"), nullable=False)
    policy_id: Mapped[int] = mapped_column(ForeignKey("growth_policy.id"), nullable=False)
    entitlement_key: Mapped[str] = mapped_column(String(160), nullable=False)
    asset: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="review", nullable=False)
    release_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class CashAccountModel(ModelMixin):
    __tablename__ = "growth_cash_account"
    __table_args__ = (UniqueConstraint("app_id", "user_id", name="uq_growth_cash_user"), CheckConstraint("available >= 0 AND frozen >= 0 AND debt >= 0", name="ck_growth_cash_balances"))
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    available: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    frozen: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    debt: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class CashLedgerModel(ModelMixin):
    __tablename__ = "growth_cash_ledger"
    __table_args__ = (UniqueConstraint("app_id", "entry_key", name="uq_growth_cash_entry"), Index("ix_growth_cash_user", "app_id", "user_id", "created_time"))
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    entry_key: Mapped[str] = mapped_column(String(128), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    frozen_delta: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    debt_delta: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reference_id: Mapped[int] = mapped_column(Integer, nullable=False)


class GiftModel(ModelMixin):
    __tablename__ = "growth_gift"
    __table_args__ = (UniqueConstraint("app_id", "sender_id", "idempotency_key", name="uq_growth_gift_once"), CheckConstraint("sender_id != recipient_id AND amount > 0", name="ck_growth_gift_valid"))
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    sender_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    policy_id: Mapped[int] = mapped_column(ForeignKey("growth_policy.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    allocations: Mapped[list] = mapped_column(JSON, nullable=False)


class GiftAllowanceModel(ModelMixin):
    __tablename__ = "growth_gift_allowance"
    __table_args__ = (UniqueConstraint("app_id", "user_id", "month", name="uq_growth_gift_month"),)
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    baseline: Mapped[int] = mapped_column(BigInteger, nullable=False)
    used: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class PayoutAccountModel(ModelMixin):
    __tablename__ = "growth_payout_account"
    __table_args__ = (UniqueConstraint("app_id", "user_id", "provider", name="uq_growth_payout_account"),)
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    encrypted_details: Mapped[str] = mapped_column(Text, nullable=False)
    masked_label: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="review", nullable=False)


class WithdrawalModel(ModelMixin):
    __tablename__ = "growth_withdrawal"
    __table_args__ = (
        UniqueConstraint("app_id", "user_id", "idempotency_key", name="uq_growth_withdrawal_once"),
        UniqueConstraint("out_bill_no", name="uq_growth_payout_bill"),
        CheckConstraint("amount_fen > 0", name="ck_growth_withdrawal_amount"),
    )
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("growth_payout_account.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    out_bill_no: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="review", nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    payee_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    provider_bill_no: Mapped[str | None] = mapped_column(String(128))
    confirmation_package: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(500))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PayoutAttemptModel(ModelMixin):
    __tablename__ = "growth_payout_attempt"
    __table_args__ = (Index("ix_growth_payout_attempt", "app_id", "withdrawal_id"),)
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    withdrawal_id: Mapped[int] = mapped_column(ForeignKey("growth_withdrawal.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    detail: Mapped[str] = mapped_column(String(500), nullable=False)


class PayoutLinkModel(ModelMixin):
    __tablename__ = "growth_payout_link"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_growth_payout_link_token"),)
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    withdrawal_id: Mapped[int | None] = mapped_column(ForeignKey("growth_withdrawal.id"))
    encrypted_payload: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
