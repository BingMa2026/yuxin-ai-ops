from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin


class AgreementModel(ModelMixin):
    __tablename__ = "client_agreement"
    __table_args__ = (UniqueConstraint("app_id", "code", name="uq_agreement_code"), Index("ix_agreement_scope", "app_id", "status", "is_deleted"))
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text, default="")
    change_summary: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    has_draft: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id", ondelete="SET NULL"))


class AgreementVersionModel(ModelMixin):
    __tablename__ = "client_agreement_version"
    __table_args__ = (UniqueConstraint("app_id", "agreement_id", "version", name="uq_agreement_version"),)
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id", ondelete="RESTRICT"))
    agreement_id: Mapped[int] = mapped_column(ForeignKey("client_agreement.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    change_summary: Mapped[str] = mapped_column(String(1000))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id", ondelete="SET NULL"))


class AgreementSceneModel(ModelMixin):
    __tablename__ = "client_agreement_scene"
    __table_args__ = (UniqueConstraint("app_id", "code", name="uq_agreement_scene_code"),)
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    agreement_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    require_acceptance: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id", ondelete="SET NULL"))


class AgreementAcceptanceModel(ModelMixin):
    __tablename__ = "client_agreement_acceptance"
    __table_args__ = (Index("ix_agreement_acceptance_user", "app_id", "user_id", "created_time"),)
    app_id: Mapped[int] = mapped_column(ForeignKey("client_app.id", ondelete="RESTRICT"))
    user_id: Mapped[int] = mapped_column(ForeignKey("client_user.id", ondelete="RESTRICT"))
    scene_code: Mapped[str] = mapped_column(String(64))
    scene_revision: Mapped[int] = mapped_column(Integer)
    version_ids: Mapped[list[int]] = mapped_column(JSON)
    business_ref: Mapped[str] = mapped_column(String(128))
