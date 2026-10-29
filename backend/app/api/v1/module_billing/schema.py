from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.base_schema import BaseSchema


class ReleaseItemSchema(BaseModel):
    offset_day: int = Field(ge=0, le=3650)
    amount: int = Field(gt=0)
    account_type: Literal["activity_reward", "current_cycle", "monthly_reserve", "traffic_pack", "enterprise_pool", "manual"] = "current_cycle"


class PricingTemplateSchema(BaseModel):
    entitlement_kind: Literal["credits", "duration"] = "credits"
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=64)
    plan_type: Literal["subscription", "credit_pack"] = "subscription"
    tier_code: Literal["free", "starter", "professional", "enterprise"] | None = None
    tier_order: int = Field(default=0, ge=0, le=999)
    billing_period_days: int = Field(default=30, ge=1, le=3650)
    one_time_price_fen: int = Field(ge=0)
    recurring_price_fen: int = Field(ge=0)
    total_credits: int = Field(ge=0)
    release_plan: list[ReleaseItemSchema]
    credit_valid_days: int = Field(default=30, ge=1, le=3650)
    renewal_rule: str | None = None
    benefits: list[str] = Field(default_factory=list)
    requires_active_subscription: bool = False
    order: int = 999

    @model_validator(mode="after")
    def validate_release_total(self):
        from .plan_rules import validate_entitlement

        validate_entitlement(self.entitlement_kind, self.plan_type, self.total_credits, self.release_plan, self.requires_active_subscription)
        if sum(item.amount for item in self.release_plan) != self.total_credits:
            raise ValueError("释放计划之和必须等于总积分")
        return self


class PricingVersionCreateSchema(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=2, max_length=64)
    effective_at: datetime | None = None
    margin_baseline: float = Field(default=60, ge=0, lt=100)
    credits_per_yuan: int = Field(default=1000, gt=0, le=1_000_000)
    subscription_cycle_days: int = Field(default=30, ge=1, le=3650)
    renewal_discount_rate: float = Field(default=0.9, gt=0, le=1)
    margin_floor: float = Field(default=25, ge=0, lt=100)
    account_priority: list[Literal["activity_reward", "current_cycle", "monthly_reserve", "traffic_pack", "enterprise_pool", "manual"]] = Field(
        default_factory=lambda: ["activity_reward", "current_cycle", "monthly_reserve", "traffic_pack", "enterprise_pool", "manual"]
    )
    description: str | None = Field(default=None, max_length=1000)
    templates: list[PricingTemplateSchema] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_templates(self):
        if len({item.code for item in self.templates}) != len(self.templates):
            raise ValueError("套餐编码不能重复")
        if len(set(self.account_priority)) != len(self.account_priority):
            raise ValueError("积分扣减账户不能重复")
        return self


class PricingVersionUpdateSchema(PricingVersionCreateSchema):
    """编辑版本配置及模板，保留发布状态和已有刊例快照。"""


class PricingVersionOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    version: str
    name: str
    status: str
    effective_at: datetime | None = None
    published_at: datetime | None = None
    credit_unit_name: str
    margin_baseline: float
    credits_per_yuan: int
    subscription_cycle_days: int
    renewal_discount_rate: float
    margin_floor: float
    account_priority: list[str]
    description: str | None = None
    template_count: int = 0


class PricingTemplateOutSchema(BaseSchema):
    entitlement_kind: Literal["credits", "duration"] = "credits"
    model_config = ConfigDict(from_attributes=True)
    version_id: int
    code: str
    name: str
    plan_type: str
    tier_code: str | None = None
    tier_order: int = 0
    billing_period_days: int
    one_time_price_fen: int
    recurring_price_fen: int
    total_credits: int
    release_plan: list[dict]
    credit_valid_days: int
    renewal_rule: str | None = None
    benefits: list[str]
    requires_active_subscription: bool
    status: str
    order: int


class CatalogPlanCreateSchema(BaseModel):
    entitlement_kind: Literal["credits", "duration"] = "credits"
    template_id: int | None = None
    pricing_version_id: int
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=64)
    plan_type: Literal["subscription", "credit_pack"] = "subscription"
    tier_code: Literal["free", "starter", "professional", "enterprise"] | None = None
    tier_order: int = Field(default=0, ge=0, le=999)
    one_time_price_fen: int = Field(ge=0)
    recurring_price_fen: int = Field(ge=0)
    benefit_period_days: int = Field(default=30, ge=1, le=3650)
    total_credits: int = Field(ge=0)
    release_plan: list[ReleaseItemSchema]
    credit_valid_days: int = Field(default=30, ge=1)
    benefits: list[str] = Field(default_factory=list)
    requires_active_subscription: bool = False
    cost_budget_yuan: float | None = Field(default=None, gt=0)
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    order: int = 999
    status: Literal["draft", "on_sale", "off_sale"] = "draft"

    @model_validator(mode="after")
    def validate_plan(self):
        from .plan_rules import validate_entitlement

        validate_entitlement(self.entitlement_kind, self.plan_type, self.total_credits, self.release_plan, self.requires_active_subscription)
        if sum(item.amount for item in self.release_plan) != self.total_credits:
            raise ValueError("释放计划之和必须等于总积分")
        if self.effective_from and self.effective_until and self.effective_from >= self.effective_until:
            raise ValueError("结束时间必须晚于开始时间")
        if self.plan_type == "credit_pack" and not self.requires_active_subscription:
            self.requires_active_subscription = True
        return self


class CatalogPlanOutSchema(BaseSchema):
    entitlement_kind: Literal["credits", "duration"] = "credits"
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    template_id: int | None = None
    pricing_version_id: int
    code: str
    name: str
    plan_type: str
    tier_code: str | None = None
    tier_order: int = 0
    one_time_price_fen: int
    recurring_price_fen: int
    benefit_period_days: int
    total_credits: int
    release_plan: list[dict]
    credit_valid_days: int
    benefits: list[str]
    requires_active_subscription: bool
    cost_budget_yuan: float | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    order: int
    status: str
    effective_price_fen: int | None = None
    base_price_fen: int | None = None
    discount_amount_fen: int = 0
    purchase_type: Literal["first", "renewal"] = "first"
    strategy_name: str | None = None
    strategy_version: str | None = None
    is_current: bool = False
    requires_mode_switch: bool = False
    eligible: bool = True
    disabled_reason: str | None = None


class CatalogPlanUpdateSchema(BaseModel):
    entitlement_kind: Literal["credits", "duration"] | None = None
    name: str | None = Field(default=None, min_length=2, max_length=64)
    tier_code: Literal["free", "starter", "professional", "enterprise"] | None = None
    tier_order: int | None = Field(default=None, ge=0, le=999)
    one_time_price_fen: int | None = Field(default=None, ge=0)
    recurring_price_fen: int | None = Field(default=None, ge=0)
    benefit_period_days: int | None = Field(default=None, ge=1, le=3650)
    total_credits: int | None = Field(default=None, ge=0)
    release_plan: list[ReleaseItemSchema] | None = None
    credit_valid_days: int | None = Field(default=None, ge=1)
    benefits: list[str] | None = None
    requires_active_subscription: bool | None = None
    cost_budget_yuan: float | None = Field(default=None, gt=0)
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    order: int | None = None
    status: Literal["draft", "on_sale", "off_sale"] | None = None

    @model_validator(mode="after")
    def validate_times(self):
        nullable = {"tier_code", "cost_budget_yuan", "effective_from", "effective_until"}
        if any(getattr(self, name) is None for name in self.model_fields_set - nullable):
            raise ValueError("套餐必填配置不能设为空值")
        if self.effective_from and self.effective_until and self.effective_from >= self.effective_until:
            raise ValueError("结束时间必须晚于开始时间")
        return self


class PricingStrategyItemCreateSchema(BaseModel):
    catalog_plan_id: int
    purchase_type: Literal["first", "renewal", "all"] = "all"
    discount_rate: float = Field(default=1, gt=0, le=1)
    margin_rate: float = Field(default=60, ge=0, lt=100)
    allowed_cost_yuan: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    remark: str | None = Field(default=None, max_length=500)


class PricingStrategyItemOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    strategy_id: int
    catalog_plan_id: int
    purchase_type: str
    discount_rate: float
    execution_price_fen: int
    margin_rate: float
    allowed_cost_yuan: float
    credits_per_cost_yuan: float
    remark: str | None = None


class PricingStrategyCreateSchema(BaseModel):
    catalog_plan_id: int
    name: str = Field(min_length=2, max_length=64)
    version: str | None = Field(default=None, min_length=1, max_length=32)
    pricing_version_id: int | None = None
    scope_type: Literal["all", "new", "level", "segment", "users"] = "all"
    scope_value: dict = Field(default_factory=dict)
    purchase_type: Literal["first", "renewal", "all"] = "all"
    discount_rate: float | None = Field(default=None, gt=0, le=1)
    fixed_price_fen: int | None = Field(default=None, ge=0)
    starts_at: datetime
    ends_at: datetime
    status: Literal["active", "inactive"] = "inactive"
    description: str | None = None
    items: list[PricingStrategyItemCreateSchema] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_price(self):
        if not self.items and (self.discount_rate is None) == (self.fixed_price_fen is None):
            raise ValueError("折扣率和固定执行价必须且只能填写一个")
        if self.starts_at >= self.ends_at:
            raise ValueError("结束时间必须晚于开始时间")
        return self


class PricingStrategyOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    version: str | None = None
    pricing_version_id: int | None = None
    catalog_plan_id: int
    name: str
    purchase_type: str
    discount_rate: float | None = None
    fixed_price_fen: int | None = None
    starts_at: datetime
    ends_at: datetime
    status: str
    description: str | None = None
    scope_type: str = "all"
    scope_value: dict = Field(default_factory=dict)
    published_at: datetime | None = None
    items: list[PricingStrategyItemOutSchema] = Field(default_factory=list)


class PricingStrategyStatusSchema(BaseModel):
    status: Literal["active", "inactive"]


class CreditAccountOutSchema(BaseModel):
    available: int = 0
    reserved: int = 0
    pending: int = 0
    total_granted: int = 0
    total_consumed: int = 0


class CreditAdjustSchema(BaseModel):
    amount: int
    reason: str = Field(min_length=2, max_length=500)
    expires_in_days: int = Field(default=365, ge=1, le=3650)
    idempotency_key: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{8,64}$")


class CreditReserveSchema(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    estimated: int = Field(gt=0)


class CreditSettleSchema(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    actual: int = Field(ge=0)


class SubscriptionAdminOutSchema(BaseSchema):
    entitlement_kind: Literal["credits", "duration"] = "credits"
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    user_id: int
    username: str
    display_name: str | None = None
    catalog_plan_id: int
    plan_name: str
    status: str
    auto_renew: bool
    current_period_start: datetime
    current_period_end: datetime
    next_renewal_at: datetime | None = None
    available_credits: int = 0
    pending_credits: int = 0


class SubscriptionStatusSchema(BaseModel):
    status: Literal["active", "expired", "cancelled"]
    reason: str = Field(min_length=2, max_length=500)


class ClientSubscriptionOutSchema(BaseSchema):
    entitlement_kind: Literal["credits", "duration"] = "credits"
    model_config = ConfigDict(from_attributes=True)
    catalog_plan_id: int
    plan_name: str
    tier_code: str | None = None
    tier_order: int = 0
    status: str
    current_period_start: datetime
    current_period_end: datetime
    auto_renew: bool


class ClientCreditLedgerOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    entry_type: str
    amount: int
    balance_after: int
    reason: str | None = None
    reference_type: str | None = None
    reference_id: str | None = None
    status: str
