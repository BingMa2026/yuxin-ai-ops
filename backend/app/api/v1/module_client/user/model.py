from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import ModelMixin, UserMixin


class ClientUserModel(ModelMixin, UserMixin):
    """客户端最终用户，与运营人员 ``sys_user`` 完全分离。"""

    __tablename__ = "client_user"
    __table_args__ = (
        UniqueConstraint("app_id", "username", name="uq_client_user_app_username"),
        UniqueConstraint("app_id", "wechat_openid", name="uq_client_user_app_wechat_openid"),
        Index(
            "uq_client_user_verified_mobile",
            "app_id",
            "mobile",
            unique=True,
            postgresql_where=text("mobile_verified_at IS NOT NULL AND is_deleted = false"),
            sqlite_where=text("mobile_verified_at IS NOT NULL AND is_deleted = 0"),
        ),
        Index("ix_client_user_app_status", "app_id", "status", "is_deleted"),
        Index("ix_client_user_app_last_active", "app_id", "last_active_at"),
        Index("ix_client_user_created_deleted", "created_time", "is_deleted"),
        {"comment": "客户端最终用户表"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False, comment="客户端应用ID")
    username: Mapped[str] = mapped_column(String(32), nullable=False, comment="登录账号")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码摘要")
    wechat_openid: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="网站应用微信登录标识")
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="姓名或昵称")
    avatar: Mapped[str | None] = mapped_column(String(1000), nullable=True, comment="头像地址")
    company_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="企业名称")
    mobile: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="手机号")
    mobile_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="手机号验证时间")
    email: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="邮箱")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active", comment="active/disabled")
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0", comment="是否必须修改密码")
    active_billing_mode: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="当前生效模式 credits/duration；未选择为空")
    mode_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    auth_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1", comment="认证版本，停用或重置密码时递增")
    registration_source: Mapped[str] = mapped_column(String(32), nullable=False, default="self", server_default="self", comment="注册来源")
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), comment="注册时间")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="最后登录时间")
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="最后活跃时间")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="运营备注")
    level_code: Mapped[str] = mapped_column(String(8), nullable=False, default="LV1", server_default="LV1")
    level_score: Mapped[float] = mapped_column(Numeric(7, 2), nullable=False, default=0, server_default="0")
    level_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    level_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    tags: Mapped[list["ClientUserTagModel"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ClientUserTagModel(ModelMixin, UserMixin):
    __tablename__ = "client_user_tag"
    __table_args__ = (
        UniqueConstraint("app_id", "user_id", "name", name="uq_client_user_tag_name"),
        Index("ix_client_user_tag_app_user", "app_id", "user_id", "is_deleted"),
        Index("ix_client_user_tag_status_deleted", "status", "is_deleted"),
        Index("ix_client_user_tag_created_deleted", "created_time", "is_deleted"),
        {"comment": "客户端用户人工标签表"},
    )

    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False, comment="客户端应用ID")
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_user.id", ondelete="CASCADE"), nullable=False, comment="客户端用户ID")
    name: Mapped[str] = mapped_column(String(32), nullable=False, comment="标签名称")
    color: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="标签色语义")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active", comment="active/inactive")

    user: Mapped[ClientUserModel] = relationship(back_populates="tags")


class ClientAuthEventModel(ModelMixin):
    """客户端注册/登录安全事件，不记录密码或令牌。"""

    __tablename__ = "client_auth_event"
    __table_args__ = (
        Index("ix_client_auth_event_app_action_time", "app_id", "action", "created_time"),
        Index("ix_client_auth_event_ip_time", "request_ip", "created_time"),
        Index("ix_client_auth_event_username_time", "app_code", "username", "created_time"),
        Index("ix_client_auth_event_created_deleted", "created_time", "is_deleted"),
        {"comment": "客户端注册登录安全事件"},
    )

    app_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("client_app.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("client_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    app_code: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False, comment="register/login")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_ip: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ClientUserLevelConfigModel(ModelMixin, UserMixin):
    __tablename__ = "client_user_level_config"
    __table_args__ = (
        UniqueConstraint("app_id", name="uq_client_level_config_app"),
        Index("ix_client_level_config_app_status", "app_id", "status", "is_deleted"),
        {"comment": "客户端用户等级规则"},
    )
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    rules: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")


class ClientUserLevelHistoryModel(ModelMixin):
    __tablename__ = "client_user_level_history"
    __table_args__ = (
        Index("ix_client_level_history_app_user", "app_id", "user_id", "created_time"),
        {"comment": "客户端用户等级变更历史"},
    )
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_user.id", ondelete="CASCADE"), nullable=False)
    old_level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    new_level: Mapped[str] = mapped_column(String(8), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(7, 2), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)


class ClientUserSegmentModel(ModelMixin, UserMixin):
    __tablename__ = "client_user_segment"
    __table_args__ = (
        UniqueConstraint("app_id", "name", name="uq_client_user_segment_name"),
        Index("ix_client_user_segment_app_status", "app_id", "status", "is_deleted"),
        {"comment": "客户端动态用户分群"},
    )
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    filters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
