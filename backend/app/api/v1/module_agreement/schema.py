from datetime import datetime
from html import unescape
from typing import Literal

import bleach
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.base_schema import BaseSchema

TAGS = ["p", "br", "h1", "h2", "h3", "h4", "strong", "b", "em", "i", "u", "s", "blockquote", "ol", "ul", "li", "a", "table", "thead", "tbody", "tr", "td", "th", "hr"]
CODE = r"^[a-z][a-z0-9_]{1,63}$"
REQUIRED_SCENES = {"auth", "membership_purchase", "credit_purchase"}


def clean_content(value: str) -> str:
    return bleach.clean(
        value,
        tags=TAGS,
        attributes={"a": ["href", "title"], "td": ["colspan", "rowspan"], "th": ["colspan", "rowspan"], "ol": ["start"]},
        protocols=["https", "mailto"],
        strip=True,
        strip_comments=True,
    )


def has_text(value: str) -> bool:
    return bool(unescape(bleach.clean(value, tags=[], strip=True)).replace("\u200b", "").strip())


class DraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(pattern=CODE)
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(default="", max_length=500000)
    change_summary: str = Field(default="", max_length=1000)
    revision: int = Field(default=0, ge=0)

    @field_validator("content")
    @classmethod
    def sanitize(cls, value: str) -> str:
        return clean_content(value)


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


class AgreementOut(BaseSchema):
    app_id: int
    code: str
    title: str
    content: str
    change_summary: str
    status: Literal["draft", "published", "archived"]
    current_version: int
    has_draft: bool
    revision: int
    updated_by: int | None


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    version: int
    title: str
    content: str
    change_summary: str
    published_at: datetime
    published_by: int | None


class SceneInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(pattern=CODE)
    name: str = Field(min_length=1, max_length=120)
    agreement_ids: list[int] = Field(min_length=1, max_length=30)
    require_acceptance: bool = True
    revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def valid_bindings(self):
        if len(set(self.agreement_ids)) != len(self.agreement_ids) or any(i <= 0 for i in self.agreement_ids):
            raise ValueError("请选择不重复的协议")
        if self.code in REQUIRED_SCENES and not self.require_acceptance:
            raise ValueError("注册和购买场景必须确认协议")
        return self


class SceneOut(BaseSchema):
    app_id: int
    code: str
    name: str
    agreement_ids: list[int]
    require_acceptance: bool
    revision: int


class PublicAgreement(BaseModel):
    code: str
    version_id: int
    version: int
    title: str
    content: str
    published_at: datetime


class PublicScene(BaseModel):
    code: str
    name: str
    revision: int
    require_acceptance: bool
    agreements: list[PublicAgreement]


class AcceptanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_revision: int = Field(ge=1)
    version_ids: list[int] = Field(min_length=1, max_length=30)


class AcceptanceOut(BaseSchema):
    user_id: int
    scene_code: str
    scene_revision: int
    version_ids: list[int]
    business_ref: str
