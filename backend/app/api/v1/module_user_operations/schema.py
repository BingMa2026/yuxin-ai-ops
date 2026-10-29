from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.base_schema import BaseSchema
from app.utils.xss_util import sanitize_html

TicketKind = Literal["complaint", "feedback"]
TicketPriority = Literal["low", "normal", "high", "urgent"]
TicketStatus = Literal["pending", "processing", "waiting_user", "resolved", "closed"]


class AttachmentSchema(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=1000)
    size: int | None = Field(default=None, ge=0, le=10 * 1024 * 1024)


class TicketCreateSchema(BaseModel):
    kind: TicketKind
    category: Literal["service", "billing", "security", "bug", "feature", "experience", "ai_quality", "other"]
    subject: str = Field(min_length=2, max_length=120)
    content: str = Field(min_length=2, max_length=10000)
    attachments: list[AttachmentSchema] = Field(default_factory=list, max_length=5)
    priority: TicketPriority = "normal"


class TicketUpdateSchema(BaseModel):
    priority: TicketPriority | None = None
    status: TicketStatus | None = None
    assignee_id: int | None = Field(default=None, gt=0)
    adopted: bool | None = None
    value_grade: Literal["S", "A", "B", "C"] | None = None


class TicketMessageCreateSchema(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    attachments: list[AttachmentSchema] = Field(default_factory=list, max_length=5)
    internal: bool = False


class TicketMessageOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    ticket_id: int
    sender_type: str
    sender_id: int
    content: str
    attachments: list[dict]
    internal: bool


class TicketOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    user_id: int
    username: str | None = None
    display_name: str | None = None
    ticket_no: str
    kind: TicketKind
    category: str
    subject: str
    content: str
    attachments: list[dict]
    priority: TicketPriority
    status: TicketStatus
    assignee_id: int | None = None
    sla_due_at: datetime
    last_replied_at: datetime | None = None
    resolved_at: datetime | None = None
    adopted: bool
    value_grade: str | None = None
    messages: list[TicketMessageOutSchema] = Field(default_factory=list)


class MessageTemplateCreateSchema(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=2, max_length=120)
    content: str = Field(min_length=2, max_length=10000)
    content_type: Literal["plain_text", "rich_text"] = "rich_text"
    status: Literal["active", "inactive"] = "active"

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        return sanitize_html(value)


class MessageTemplateUpdateSchema(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=64)
    title: str | None = Field(default=None, min_length=2, max_length=120)
    content: str | None = Field(default=None, min_length=2, max_length=10000)
    content_type: Literal["plain_text", "rich_text"] | None = None
    status: Literal["active", "inactive"] | None = None

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str | None) -> str | None:
        return sanitize_html(value) if value is not None else value


class MessageTemplateOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    name: str
    title: str
    content: str
    content_type: str = "plain_text"
    status: str


class CampaignCreateSchema(BaseModel):
    template_id: int | None = Field(default=None, gt=0)
    name: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=2, max_length=120)
    content: str = Field(min_length=2, max_length=10000)
    content_type: Literal["plain_text", "rich_text"] = "rich_text"
    audience_type: Literal["all", "new", "level", "segment", "users"]
    audience_value: dict = Field(default_factory=dict)
    scheduled_at: datetime | None = None
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    send_now: bool = False

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        return sanitize_html(value)

    @model_validator(mode="after")
    def validate_audience(self):
        if self.audience_type == "level" and not self.audience_value.get("level_codes"):
            raise ValueError("请选择用户等级")
        if self.audience_type == "segment" and not self.audience_value.get("segment_id"):
            raise ValueError("请选择用户分群")
        if self.audience_type == "users" and not self.audience_value.get("user_ids"):
            raise ValueError("请选择用户")
        if self.scheduled_at and self.scheduled_at <= datetime.now(self.scheduled_at.tzinfo):
            raise ValueError("定时发送时间必须晚于当前时间")
        return self


class CampaignUpdateSchema(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=64)
    title: str | None = Field(default=None, min_length=2, max_length=120)
    content: str | None = Field(default=None, min_length=2, max_length=10000)
    content_type: Literal["plain_text", "rich_text"] | None = None
    audience_type: Literal["all", "new", "level", "segment", "users"] | None = None
    audience_value: dict | None = None
    scheduled_at: datetime | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str | None) -> str | None:
        return sanitize_html(value) if value is not None else value


class CampaignOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    template_id: int | None = None
    name: str
    title: str
    content: str
    content_type: str = "plain_text"
    audience_type: str
    audience_value: dict
    scheduled_at: datetime | None = None
    timezone: str = "Asia/Shanghai"
    sent_at: datetime | None = None
    status: str
    target_count: int
    delivered_count: int
    read_count: int
    failed_count: int = 0
    cancelled_at: datetime | None = None


class CampaignAudiencePreviewSchema(BaseModel):
    audience_type: Literal["all", "new", "level", "segment", "users"]
    audience_value: dict = Field(default_factory=dict)


class CampaignAudiencePreviewOutSchema(BaseModel):
    target_count: int
    sample_users: list[dict] = Field(default_factory=list)


class ClientInboxMessageOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    message_type: str
    title: str
    content: str
    content_type: str = "plain_text"
    deep_link: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    delivered_at: datetime
    read_at: datetime | None = None
    status: str


class MessageDeliveryOutSchema(ClientInboxMessageOutSchema):
    user_id: int
    username: str
    display_name: str | None = None
    campaign_id: int | None = None
