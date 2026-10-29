from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, UserMixin


class ClientSupportTicketModel(ModelMixin, UserMixin):
    __tablename__ = "client_support_ticket"
    __table_args__ = (
        UniqueConstraint("app_id", "ticket_no", name="uq_client_support_ticket_no"),
        Index("ix_support_ticket_app_status", "app_id", "status", "is_deleted"),
        Index("ix_support_ticket_app_user", "app_id", "user_id", "created_time"),
        {"comment": "客户端工单与反馈"},
    )
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False)
    ticket_no: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal", server_default="normal")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    assignee_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sys_user.id", ondelete="SET NULL"), nullable=True)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    adopted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    value_grade: Mapped[str | None] = mapped_column(String(1), nullable=True)


class ClientSupportMessageModel(ModelMixin):
    __tablename__ = "client_support_message"
    __table_args__ = (
        Index("ix_support_message_app_ticket", "app_id", "ticket_id", "created_time"),
        {"comment": "客户端工单会话"},
    )
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_support_ticket.id", ondelete="CASCADE"), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_id: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class ClientMessageTemplateModel(ModelMixin, UserMixin):
    __tablename__ = "client_message_template"
    __table_args__ = (
        UniqueConstraint("app_id", "name", name="uq_client_message_template_name"),
        Index("ix_client_message_template_app", "app_id", "status", "is_deleted"),
        {"comment": "客户端站内消息模板"},
    )
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False, default="rich_text", server_default="plain_text")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")


class ClientMessageCampaignModel(ModelMixin, UserMixin):
    __tablename__ = "client_message_campaign"
    __table_args__ = (
        Index("ix_client_campaign_app_status", "app_id", "status", "scheduled_at", "is_deleted"),
        {"comment": "客户端站内消息触达任务"},
    )
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("client_message_template.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False, default="rich_text", server_default="plain_text")
    audience_type: Mapped[str] = mapped_column(String(20), nullable=False)
    audience_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    delivered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    read_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClientMessageDeliveryModel(ModelMixin):
    __tablename__ = "client_message_delivery"
    __table_args__ = (
        UniqueConstraint("campaign_id", "user_id", name="uq_client_message_delivery_campaign_user"),
        Index("ix_client_message_delivery_inbox", "app_id", "user_id", "read_at", "created_time"),
        {"comment": "客户端站内消息投递"},
    )
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("client_message_campaign.id", ondelete="CASCADE"), nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_user.id", ondelete="CASCADE"), nullable=False)
    message_type: Mapped[str] = mapped_column(String(24), nullable=False, default="campaign", server_default="campaign")
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False, default="plain_text", server_default="plain_text")
    deep_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="delivered", server_default="delivered")
