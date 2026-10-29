from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SpeechConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_model_id: int | None = Field(default=None, gt=0)
    status: Literal["active", "inactive"] = "inactive"
    max_duration_seconds: int = Field(default=60, ge=5, le=60)
    daily_limit_seconds: int = Field(default=600, ge=60, le=3600)
    revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def enabled_model(self):
        if self.status == "active" and self.catalog_model_id is None:
            raise ValueError("请先选择语音识别模型")
        return self


class SpeechConfigOut(SpeechConfigInput):
    model_config = ConfigDict(from_attributes=True)


class SpeechCapability(BaseModel):
    available: bool
    reason: str | None = None
    max_duration_seconds: int = 60
    daily_limit_seconds: int = 600


class SpeechResult(BaseModel):
    text: str
    duration_ms: int


class SpeechModelOption(BaseModel):
    id: int
    name: str
    provider_name: str
    provider_model_id: str
    status: str
