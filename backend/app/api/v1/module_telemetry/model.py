from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin


class TelemetryEventModel(ModelMixin):
    """Privacy-safe client operation facts used by later operating dashboards."""

    __tablename__ = "telemetry_event"
    __table_args__ = (
        UniqueConstraint("app_id", "event_id", name="uq_telemetry_event_app_event"),
        Index("ix_telemetry_event_app_type_time", "app_id", "event_type", "occurred_at"),
        Index("ix_telemetry_event_app_user_time", "app_id", "user_id", "occurred_at"),
        Index("ix_telemetry_event_created_deleted", "created_time", "is_deleted"),
        {"comment": "客户端运营遥测事件（不保存业务正文与本地路径）"},
    )

    app_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("client_app.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("client_user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    client_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    project_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    task_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    event_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
