from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.module_agreement.schema import AcceptanceInput
from app.api.v1.module_billing.mode_switch.schema import ModeSwitchConfirmation
from app.core.base_schema import BaseSchema


class PaymentOrderCreate(BaseModel):
    replaces_order_no: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_.:-]+$")
    mode_switch_confirmation: ModeSwitchConfirmation | None = None
    agreement_acceptance: AcceptanceInput | None = None
    catalog_plan_id: int = Field(gt=0)
    provider: Literal["wechat", "alipay"]
    idempotency_key: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{8,128}$")
    auto_renew: bool = False
    return_url: str | None = Field(default=None, max_length=1000)


class PaymentOrderOut(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    user_id: int
    order_no: str
    catalog_plan_id: int
    purchase_type: str
    provider: str
    amount_fen: int
    currency: str
    plan_snapshot: dict
    strategy_snapshot: dict | None = None
    mode_switch: dict | None = None
    status: str
    pay_url: str | None = None
    expires_at: datetime
    paid_at: datetime | None = None
    closed_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    replaces_order_no: str | None = None
    replaced_by_order_no: str | None = None
    failure_reason: str | None = None
    auto_renew_requested: bool


class PaymentOrderStatus(BaseModel):
    order_no: str
    status: str
    paid_at: datetime | None = None


class PaymentOrderCancel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    reason: str = Field(default="用户取消购买", min_length=2, max_length=500, pattern=r"\S")


class PaymentCapability(BaseModel):
    provider: Literal["wechat", "alipay"]
    name: str
    enabled: bool
    configured: bool
    supports_auto_renew: bool
