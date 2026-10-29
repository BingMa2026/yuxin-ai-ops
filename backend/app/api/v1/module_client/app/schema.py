import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.base_schema import BaseQueryParam, BaseSchema

ServiceMode = Literal["credits_only", "duration_only", "user_choice"]

ClientAppStatus = Literal["draft", "active", "inactive"]


class ClientAppCreateSchema(BaseModel):
    name: str = Field(min_length=2, max_length=64, description="应用名称")
    code: str = Field(min_length=2, max_length=64, description="稳定应用编码")
    logo: str | None = Field(default=None, max_length=255, description="Logo地址")
    client_version: str | None = Field(default=None, max_length=32, description="当前客户端版本")
    status: ClientAppStatus = Field(default="draft", description="应用状态")
    service_mode: ServiceMode = "user_choice"
    platform_model_enabled: bool = True
    registration_enabled: bool = Field(default=False, description="是否允许注册")
    order: int = Field(default=999, ge=1, le=999, description="显示排序")
    description: str | None = Field(default=None, max_length=1000, description="应用简介")

    @model_validator(mode="before")
    @classmethod
    def legacy_mode(cls, values):
        values = dict(values)
        if "platform_model_enabled" in values and not isinstance(values["platform_model_enabled"], bool):
            raise ValueError("平台模型配置必须为布尔值")
        if "service_mode" not in values and "platform_model_enabled" in values:
            values["service_mode"] = "credits_only" if values["platform_model_enabled"] else "duration_only"
        values["platform_model_enabled"] = values.get("service_mode", "user_choice") != "duration_only"
        return values

    @field_validator("name", "code")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return value.strip()

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value):
            raise ValueError("应用编码须以小写字母开头，仅允许小写字母、数字和下划线")
        return value


class ClientAppUpdateSchema(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=64)
    logo: str | None = Field(default=None, max_length=255)
    client_version: str | None = Field(default=None, max_length=32)
    status: ClientAppStatus | None = None
    service_mode: ServiceMode | None = None
    platform_model_enabled: bool | None = None
    expected_policy_version: int | None = Field(default=None, ge=1)
    registration_enabled: bool | None = None
    order: int | None = Field(default=None, ge=1, le=999)
    description: str | None = Field(default=None, max_length=1000)


class ClientAppQueryParam(BaseQueryParam):
    name: str | None = Field(default=None, json_schema_extra={"q": "like"})
    code: str | None = Field(default=None, json_schema_extra={"q": "like"})
    status: ClientAppStatus | None = Field(default=None, json_schema_extra={"q": "eq"})


class ClientAppOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    logo: str | None = None
    client_version: str | None = None
    status: ClientAppStatus
    service_mode: ServiceMode = "user_choice"
    platform_model_enabled: bool = True
    model_policy_version: int = 1
    registration_enabled: bool
    order: int
    description: str | None = None
    can_switch: bool = True
    is_current: bool = False


class ClientAppStaffGrantSchema(BaseModel):
    staff_ids: list[int] = Field(min_length=1, description="拥有该应用权限的运营人员ID")


class ClientAppStaffOptionSchema(BaseModel):
    id: int
    username: str
    name: str
    selected: bool = False


class SelectClientAppSchema(BaseModel):
    app_id: int = Field(gt=0, description="客户端应用ID")


class ClientAppContextSchema(BaseModel):
    current_app: ClientAppOutSchema | None = None
    apps: list[ClientAppOutSchema] = Field(default_factory=list)


class ClientReleaseCreateSchema(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$", max_length=32)
    channel: Literal["stable", "test"] = "test"
    release_notes: str = Field(default="", max_length=20000)
    min_supported_version: str | None = Field(
        default=None,
        pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$",
        max_length=32,
    )
    force_update: bool = False


class ClientReleaseUpdateSchema(BaseModel):
    release_notes: str | None = Field(default=None, max_length=20000)
    min_supported_version: str | None = Field(
        default=None,
        pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$",
        max_length=32,
    )
    force_update: bool | None = None


class ClientReleaseArtifactCreateSchema(BaseModel):
    artifact_type: Literal["installer", "blockmap"]
    external_url: str = Field(min_length=8, max_length=2000)
    file_name: str = Field(min_length=1, max_length=255)
    file_size: int = Field(default=0, ge=0)
    sha512: str | None = Field(default=None, min_length=64, max_length=172)
    signature_verified: bool = False


class ClientReleaseArtifactOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    release_id: int
    artifact_type: str
    source_type: str
    storage_source_id: int | None = None
    storage_path: str | None = None
    external_url: str | None = None
    file_name: str
    file_size: int
    sha512: str | None = None
    signature_verified: bool


class ClientReleaseOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    platform: str
    arch: str
    channel: str
    version: str
    release_notes: str
    min_supported_version: str | None = None
    force_update: bool
    status: str
    published_at: datetime | None = None
    artifacts: list[ClientReleaseArtifactOutSchema] = Field(default_factory=list)
