"""Typed, executable growth policies. Descriptions never participate in evaluation."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Track = Literal["usage", "promotion"]
Asset = Literal["credits", "cash"]
EventKind = Literal["daily_login", "first_task", "first_subscription", "first_traffic", "feedback", "artifact", "cocreate"]
Metric = Literal["net_paid_fen", "active_days", "artifacts", "feedback", "registrations", "first_users", "first_payers", "conversion_rate", "retention_rate", "compliance_rate", "refund_rate"]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class MetricCondition(StrictSchema):
    metric: Metric
    operator: Literal["gte", "lte"] = "gte"
    value: Decimal = Field(ge=0, le=1_000_000_000)


class ScoreDimension(StrictSchema):
    metric: Literal["net_paid_fen", "active_days", "artifacts", "feedback"]
    weight: int = Field(ge=0, le=100)
    cap: Decimal = Field(gt=0, le=1_000_000_000)


class GradeDefinition(StrictSchema):
    code: str = Field(pattern=r"^[RA][123]$")
    name: str = Field(min_length=1, max_length=32)
    min_score: Decimal = Field(default=0, ge=0, le=100)
    conditions: list[MetricCondition] = Field(default_factory=list, max_length=12)


class GradePolicy(StrictSchema):
    track: Track
    window_days: int = Field(default=90, ge=7, le=730)
    cadence: Literal["daily", "weekly", "monthly"] = "monthly"
    downgrade_periods: int = Field(default=2, ge=1, le=12)
    retention_min_samples: int = Field(default=5, ge=1, le=1000)
    compliance_min_coverage: int = Field(default=80, ge=1, le=100)
    dimensions: list[ScoreDimension] = Field(default_factory=list, max_length=4)
    grades: list[GradeDefinition] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def valid_track(self):
        prefix = "R" if self.track == "usage" else "A"
        if [g.code for g in self.grades] != [f"{prefix}{n}" for n in (1, 2, 3)]:
            raise ValueError("等级必须按对应体系的1、2、3顺序配置")
        usage_metrics = {"net_paid_fen", "active_days", "artifacts", "feedback"}
        for grade in self.grades:
            if len({c.metric for c in grade.conditions}) != len(grade.conditions):
                raise ValueError("同一等级不能重复配置指标")
            if any((c.metric in usage_metrics) != (self.track == "usage") for c in grade.conditions):
                raise ValueError("指标不属于当前等级体系")
            if any(c.metric.endswith("rate") and c.value > 100 for c in grade.conditions):
                raise ValueError("比例指标不能超过100%")
        if self.track == "usage":
            if sum(d.weight for d in self.dimensions) != 100 or len({d.metric for d in self.dimensions}) != len(self.dimensions):
                raise ValueError("评分维度不能重复，权重合计必须为100")
            scores = [g.min_score for g in self.grades]
            if scores[0] != 0 or not scores[0] < scores[1] < scores[2] or self.grades[0].conditions:
                raise ValueError("R1从0分开始且无附加条件，升级分数必须严格递增")
        elif self.dimensions:
            raise ValueError("推广等级使用指标门槛，不使用加权评分")
        return self


class RightsPolicy(StrictSchema):
    credit_valid_days: int = Field(default=90, ge=1, le=3650)
    gift_enabled: bool = False
    gift_reward_credits: bool = False
    gift_requires_subscription: bool = True
    gift_minimum: int = Field(default=10000, ge=1, le=1_000_000_000)
    gift_daily_count: int = Field(default=5, ge=1, le=100)
    gift_monthly_percent: int = Field(default=20, ge=1, le=100)
    withdrawal_enabled: bool = False
    withdrawal_min_fen: int = Field(default=10000, ge=100, le=100_000_000)
    withdrawal_max_fen: int = Field(default=100000, ge=100, le=100_000_000)
    withdrawal_daily_fen: int = Field(default=300000, ge=100, le=100_000_000)
    withdrawal_monthly_fen: int = Field(default=2000000, ge=100, le=1_000_000_000)
    withdrawal_daily_count: int = Field(default=3, ge=1, le=100)

    @model_validator(mode="after")
    def ordered_limits(self):
        if not self.withdrawal_min_fen <= self.withdrawal_max_fen <= self.withdrawal_daily_fen <= self.withdrawal_monthly_fen:
            raise ValueError("提现下限、单次上限、日限额、月限额必须依次递增")
        return self


class RewardAction(StrictSchema):
    recipient: Literal["actor", "inviter"]
    asset: Asset
    calculation: Literal["fixed", "paid_percent"] = "fixed"
    amount: int = Field(default=0, ge=0, le=100_000_000)
    percent: Decimal = Field(default=0, ge=0, le=100, decimal_places=4)
    grade_percent: dict[str, Decimal] = Field(default_factory=dict)
    credits_per_yuan: int = Field(default=100, ge=1, le=100000)
    maximum: int = Field(default=100000, ge=1, le=100_000_000)

    @model_validator(mode="after")
    def valid_rates(self):
        if any(k not in {"ungraded", "A1", "A2", "A3", "R1", "R2", "R3"} or not v.is_finite() or not 0 <= v <= 100 for k, v in self.grade_percent.items()):
            raise ValueError("等级比例无效")
        if self.calculation == "fixed" and self.amount <= 0:
            raise ValueError("固定奖励数量必须大于0")
        return self


class IncentivePolicy(StrictSchema):
    event: EventKind
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    mode: Literal["auto", "review", "simulation"] = "review"
    feedback_grade: Literal["S", "A", "B", "C"] | None = None
    usage_grades: list[Literal["R1", "R2", "R3"]] = Field(default_factory=list)
    promotion_grades: list[Literal["ungraded", "A1", "A2", "A3"]] = Field(default_factory=list)
    require_subscription: bool = False
    priority: int = Field(default=100, ge=0, le=1000)
    stackable: bool = False
    daily_limit: int = Field(default=3, ge=1, le=1000)
    monthly_limit: int = Field(default=30, ge=1, le=10000)
    observe_days: int = Field(default=0, ge=0, le=365)
    budget_credits: int = Field(default=0, ge=0, le=2_000_000_000)
    budget_cash_fen: int = Field(default=0, ge=0, le=2_000_000_000)
    actions: list[RewardAction] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def valid_actions(self):
        if self.feedback_grade == "S" and self.mode == "auto":
            raise ValueError("S级反馈必须经过奖励复核，不支持自动到账")
        pairs = [(a.recipient, a.asset) for a in self.actions]
        if len(set(pairs)) != len(pairs):
            raise ValueError("同一对象的同类奖励请合并为一个动作")
        if any(a.calculation == "paid_percent" for a in self.actions) and self.event not in {"first_subscription", "first_traffic"}:
            raise ValueError("实付比例只适用于付费事件")
        if self.feedback_grade and self.event != "feedback":
            raise ValueError("反馈价值分级只能用于反馈规则")
        return self


class RuleDraftIn(StrictSchema):
    kind: Literal["usage", "promotion", "rights", "incentive"]
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=80)
    config: GradePolicy | RightsPolicy | IncentivePolicy

    @model_validator(mode="after")
    def matching_kind(self):
        valid = (
            (isinstance(self.config, GradePolicy) and self.kind == self.config.track and self.key == self.kind)
            or (isinstance(self.config, RightsPolicy) and self.kind == "rights" and self.key == "rights")
            or (isinstance(self.config, IncentivePolicy) and self.kind == "incentive" and self.key not in {"usage", "promotion", "rights"})
        )
        if not valid:
            raise ValueError("规则类别与配置不匹配")
        return self


class PublishIn(StrictSchema):
    effective_at: datetime


class BindInviteIn(StrictSchema):
    code: str = Field(min_length=4, max_length=1024)


class ReviewIn(StrictSchema):
    approved: bool
    reason: str = Field(min_length=2, max_length=500)


class TaskClaimIn(StrictSchema):
    local_task_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    project_ref: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    kind: Literal["tender_analysis", "full_review", "cocreate"]


class TaskCompleteIn(StrictSchema):
    result: Literal["completed", "failed", "cancelled"]
    artifact_ref: str | None = Field(default=None, min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class TransferIn(StrictSchema):
    recipient_code: str = Field(min_length=4, max_length=32)
    amount: int = Field(gt=0, le=1_000_000_000)
    password: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class WithdrawalIn(StrictSchema):
    account_id: int = Field(gt=0)
    amount_fen: int = Field(gt=0, le=100_000_000)
    password: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class AlipayAccountIn(StrictSchema):
    account: str = Field(min_length=5, max_length=128)
    name: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PasswordIn(StrictSchema):
    password: str = Field(min_length=1, max_length=128)


class WechatAuthorizeIn(StrictSchema):
    token: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class WechatExchangeIn(WechatAuthorizeIn):
    sdk_url: str = Field(default="", max_length=2048)
    code: str = Field(min_length=8, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")


class RefundSyncIn(StrictSchema):
    order_no: str = Field(min_length=4, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    refund_no: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_*-]+$")
