from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import ModelMixin, UserMixin

if TYPE_CHECKING:
    from app.api.v1.module_system.user.model import UserModel


class ClientAppModel(ModelMixin, UserMixin):
    """需要独立运营和数据隔离的客户端应用。"""

    __tablename__ = "client_app"
    __table_args__ = (
        Index("ix_client_app_status_deleted", "status", "is_deleted"),
        Index("ix_client_app_created_deleted", "created_time", "is_deleted"),
        {"comment": "客户端应用表"},
    )

    def __init__(self, **kwargs):
        if "service_mode" not in kwargs and "platform_model_enabled" in kwargs:
            kwargs["service_mode"] = "credits_only" if kwargs["platform_model_enabled"] else "duration_only"
        super().__init__(**kwargs)

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True, comment="稳定应用编码")
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="应用名称")
    logo: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Logo地址")
    client_version: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="当前客户端版本")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft", comment="draft/active/inactive")
    platform_model_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", comment="启用平台模型及积分；关闭后使用自配模型与订阅时长")
    service_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="user_choice", server_default="user_choice", comment="credits_only/duration_only/user_choice")
    model_policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    registration_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0", comment="是否允许注册")
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=999, server_default="999", comment="显示排序")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="应用简介")

    staff_bindings: Mapped[list["StaffAppModel"]] = relationship(back_populates="app", cascade="all, delete-orphan")


class ClientAppReleaseModel(ModelMixin, UserMixin):
    """桌面客户端发布版本。发布后内容只读，撤回仅停止分发。"""

    __tablename__ = "client_app_release"
    __table_args__ = (
        UniqueConstraint("app_id", "channel", "version", name="uq_client_app_release_version"),
        Index("ix_client_app_release_latest", "app_id", "platform", "arch", "channel", "status", "published_at"),
        {"comment": "客户端版本发布表"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False, default="windows", server_default="windows")
    arch: Mapped[str] = mapped_column(String(20), nullable=False, default="x64", server_default="x64")
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="test", server_default="test")
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    release_notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    min_supported_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    force_update: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClientAppReleaseArtifactModel(ModelMixin, UserMixin):
    """客户端发布制品；可来自平台存储或 HTTPS 外链。"""

    __tablename__ = "client_app_release_artifact"
    __table_args__ = (
        UniqueConstraint("release_id", "artifact_type", name="uq_client_app_release_artifact_type"),
        Index("ix_client_app_release_artifact_release", "release_id", "is_deleted"),
        {"comment": "客户端版本制品表"},
    )

    release_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app_release.id", ondelete="CASCADE"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="installer/blockmap")
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="upload/external")
    storage_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("storage_source.id", ondelete="SET NULL"), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    sha512: Mapped[str | None] = mapped_column(String(172), nullable=True)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class StaffAppModel(ModelMixin):
    """运营人员可管理的客户端应用范围。"""

    __tablename__ = "sys_user_app"
    __table_args__ = (
        UniqueConstraint("staff_id", "app_id", name="uq_sys_user_app_staff_app"),
        Index("ix_sys_user_app_staff_status", "staff_id", "status", "is_deleted"),
        Index("ix_sys_user_app_app_status", "app_id", "status", "is_deleted"),
        Index("ix_sys_user_app_created_deleted", "created_time", "is_deleted"),
        {"comment": "运营人员客户端应用授权表"},
    )

    staff_id: Mapped[int] = mapped_column(Integer, ForeignKey("sys_user.id", ondelete="CASCADE"), nullable=False, comment="运营人员ID")
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False, comment="客户端应用ID")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0", comment="默认应用")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active", comment="active/inactive")

    app: Mapped[ClientAppModel] = relationship(back_populates="staff_bindings")
    staff: Mapped["UserModel"] = relationship(foreign_keys=[staff_id])
