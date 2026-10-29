import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.api.v1.module_agreement.schema import AcceptanceInput
from app.core.base_schema import BaseQueryParam, BaseSchema
from app.core.validator import DateTimeStr

ClientUserStatus = Literal["active", "disabled"]


class ClientUserBaseSchema(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    avatar: str | None = Field(default=None, max_length=1000)
    company_name: str | None = Field(default=None, max_length=128)
    mobile: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None


class ClientUserRegisterSchema(ClientUserBaseSchema):
    agreement_acceptance: AcceptanceInput | None = None
    invite_code: str | None = Field(default=None, min_length=4, max_length=1024)
    app_code: str = Field(min_length=2, max_length=64)
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    mobile: str = Field(pattern=r"^1[3-9]\d{9}$")
    sms_code: str = Field(pattern=r"^\d{6}$")

    @field_validator("app_code", "username")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,31}", value):
            raise ValueError("账号须以字母开头，3-32位，仅允许字母、数字、_ . -")
        return value

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if not re.search(r"[a-z]", value) or not re.search(r"[A-Z]", value) or not re.search(r"\d", value):
            raise ValueError("密码至少8位，且必须包含大写字母、小写字母和数字")
        return value


class ClientUserLoginSchema(BaseModel):
    app_code: str = Field(min_length=2, max_length=64)
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)

    @field_validator("app_code", "username")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().lower()


class ClientSmsLoginSchema(BaseModel):
    app_code: str = Field(min_length=2, max_length=64)
    mobile: str = Field(pattern=r"^1[3-9]\d{9}$")
    sms_code: str = Field(pattern=r"^\d{6}$")


class ClientRefreshSchema(BaseModel):
    refresh_token: str = Field(min_length=1)


class ClientPasswordChangeSchema(BaseModel):
    old_password: str = Field(min_length=6, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class ClientUserUpdateSchema(ClientUserBaseSchema):
    description: str | None = Field(default=None, max_length=1000)


class ClientUserAdminUpdateSchema(ClientUserUpdateSchema):
    status: ClientUserStatus | None = None


class ClientUserStatusSchema(BaseModel):
    status: ClientUserStatus
    reason: str = Field(min_length=2, max_length=500)


class ClientUserTagCreateSchema(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    color: str | None = Field(default=None, max_length=20)


class ClientUserTagOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)

    app_id: int
    user_id: int
    name: str
    color: str | None = None
    status: str


class ClientUserOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)

    app_id: int
    username: str
    display_name: str | None = None
    avatar: str | None = None
    company_name: str | None = None
    mobile: str | None = None
    mobile_verified_at: DateTimeStr | None = None
    email: str | None = None
    status: ClientUserStatus
    must_change_password: bool
    registration_source: str
    registered_at: DateTimeStr
    last_login_at: DateTimeStr | None = None
    last_active_at: DateTimeStr | None = None
    description: str | None = None
    tags: list[ClientUserTagOutSchema] = Field(default_factory=list)
    current_subscription: str | None = None
    current_subscription_tier: str | None = None
    subscription_status: str | None = None
    subscription_expires_at: DateTimeStr | None = None
    available_credits: int = 0
    pending_credits: int = 0
    total_paid_fen: int = 0
    model_calls: int = 0
    token_usage: int = 0
    credit_usage: int = 0
    failed_calls: int = 0
    level_code: str = "LV1"
    usage_grade: str = "R1"
    promotion_grade: str = "ungraded"
    level_score: float = 0
    level_evaluated_at: DateTimeStr | None = None
    level_metrics: dict = Field(default_factory=dict)


class ClientUserQueryParam(BaseQueryParam):
    keyword: str | None = None
    status: ClientUserStatus | None = Field(default=None, json_schema_extra={"q": "eq"})
    segment: str | None = None
    registered_at: list[DateTimeStr] | None = None
    last_active_at: list[DateTimeStr] | None = None
    subscription_status: str | None = Field(default=None, max_length=20)
    catalog_plan_id: int | None = Field(default=None, gt=0)
    min_credits: int | None = Field(default=None, ge=0)
    max_credits: int | None = Field(default=None, ge=0)
    tag: str | None = Field(default=None, max_length=32)
    level_code: Literal["LV1", "LV2", "LV3", "LV4", "LV5"] | None = None
    usage_grade: Literal["R1", "R2", "R3"] | None = None
    promotion_grade: Literal["ungraded", "A1", "A2", "A3"] | None = None
    segment_id: int | None = Field(default=None, gt=0)


class TemporaryPasswordOutSchema(BaseModel):
    temporary_password: str
    must_change_password: bool = True


class ClientLoginOutSchema(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    must_change_password: bool
    user: ClientUserOutSchema


class ClientUserActivitySchema(BaseModel):
    active_billing_mode: Literal["credits", "duration"] | None = None
    mode_version: int = 1
    subscription: dict | None = None
    subscription_cycles: list[dict] = Field(default_factory=list)
    orders: list[dict] = Field(default_factory=list)
    credit_ledger: list[dict] = Field(default_factory=list)
    model_usage: list[dict] = Field(default_factory=list)
    security_events: list[dict] = Field(default_factory=list)
    expiring_credits: int = 0
    project_count: int = 0
    generated_at: datetime
    risk_flags: list[dict] = Field(default_factory=list)
    support_tickets: list[dict] = Field(default_factory=list)
    activity_trend: list[dict] = Field(default_factory=list)


class UserLevelConfigSchema(BaseModel):
    dimensions: list[dict]
    levels: list[dict]

    @field_validator("dimensions")
    @classmethod
    def validate_dimensions(cls, value: list[dict]) -> list[dict]:
        if not value or sum(int(item.get("weight", 0)) for item in value) != 100:
            raise ValueError("等级维度权重之和必须为100")
        if any(float(item.get("cap", 0)) <= 0 for item in value):
            raise ValueError("等级维度满分值必须大于0")
        return value

    @field_validator("levels")
    @classmethod
    def validate_levels(cls, value: list[dict]) -> list[dict]:
        codes = [item.get("code") for item in value]
        scores = [float(item.get("min_score", -1)) for item in value]
        if codes != ["LV1", "LV2", "LV3", "LV4", "LV5"] or scores != sorted(scores) or scores[0] != 0:
            raise ValueError("等级必须按LV1至LV5配置且阈值递增，LV1从0分开始")
        return value


class UserLevelConfigOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    version: int
    rules: dict
    status: str


class UserSegmentCreateSchema(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    filters: dict


class UserSegmentOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    name: str
    description: str | None = None
    filters: dict
    status: str
    matched_count: int = 0
