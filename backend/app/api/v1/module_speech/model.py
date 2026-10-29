from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin


class AppSpeechConfigModel(ModelMixin):
    __tablename__ = "app_speech_config"
    __table_args__ = (UniqueConstraint("app_id", name="uq_speech_config_app"),)
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    catalog_model_id: Mapped[int | None] = mapped_column(ForeignKey("model_catalog.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20), default="inactive", nullable=False)
    max_duration_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    daily_limit_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class SpeechUsageModel(ModelMixin):
    __tablename__ = "speech_usage"
    __table_args__ = (UniqueConstraint("app_id", "user_id", "request_id", name="uq_speech_request"), Index("ix_speech_user_time", "app_id", "user_id", "created_time"))
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False)
    catalog_model_id: Mapped[int] = mapped_column(ForeignKey("model_catalog.id", ondelete="RESTRICT"), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    cost_per_minute: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    estimated_cost_yuan: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    error_category: Mapped[str | None] = mapped_column(String(32))
