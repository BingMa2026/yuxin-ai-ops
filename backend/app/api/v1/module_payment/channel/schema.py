from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.base_schema import BaseSchema

PaymentProvider = Literal["wechat", "alipay"]
PaymentMode = Literal["sandbox", "production"]


class PaymentChannelUpdateSchema(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64, description="渠道名称")
    mode: PaymentMode | None = Field(default=None, description="运行环境")
    fee_rate: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=4, description="费率百分比")
    settlement_cycle: str | None = Field(default=None, min_length=1, max_length=32, description="结算周期")
    scenes: list[str] | None = Field(default=None, max_length=8, description="适用场景")
    description: str | None = Field(default=None, max_length=255, description="运营备注")
    order: int | None = Field(default=None, ge=0, description="排序")

    @field_validator("name", "settlement_cycle", "description", mode="before")
    @classmethod
    def _strip_strings(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("scenes")
    @classmethod
    def _normalize_scenes(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        result = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if not result:
            raise ValueError("至少保留一个支付场景")
        return result


class PaymentChannelToggleSchema(BaseModel):
    enabled: bool = Field(..., description="是否启用")


class PaymentChannelOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)

    provider: PaymentProvider
    name: str
    enabled: bool
    mode: PaymentMode
    fee_rate: Decimal
    settlement_cycle: str
    scenes: list[str]
    description: str | None
    order: int
    configured: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    merchant_identity: str | None = None
    notify_url_configured: bool = False
    environment_fields: list[str] = Field(default_factory=list)
    supports_auto_renew: bool = False
    app_enabled: bool = False
