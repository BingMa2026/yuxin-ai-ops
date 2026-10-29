from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin


class PaymentChannelModel(ModelMixin):
    """平台支持的支付渠道。

    这里只保存运营侧的非敏感配置；应用私钥、平台公钥、证书和 APIv3 密钥始终来自环境变量。
    """

    __tablename__: str = "pay_channel"
    __table_args__: dict[str, str] = {"comment": "支付渠道配置表"}

    provider: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True, comment="渠道标识")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="渠道名称")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0", comment="是否启用")
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="production", server_default="production", comment="运行环境")
    fee_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=0, server_default="0", comment="费率百分比")
    settlement_cycle: Mapped[str] = mapped_column(String(32), nullable=False, default="T+1", server_default="T+1", comment="结算周期")
    scenes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, comment="适用场景")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="运营备注")
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=999, server_default="999", comment="排序")
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="记录状态")


class AppPaymentChannelModel(ModelMixin):
    """平台支付渠道对客户端应用的显式授权。"""

    __tablename__: str = "app_payment_channel"
    __table_args__ = (
        UniqueConstraint("app_id", "channel_id", name="uq_app_payment_channel"),
        Index("ix_app_payment_channel_app_enabled", "app_id", "enabled", "is_deleted"),
        Index("ix_app_payment_channel_created_deleted", "created_time", "is_deleted"),
        {"comment": "客户端应用支付渠道绑定表"},
    )

    app_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("client_app.id", ondelete="RESTRICT"),
        nullable=False,
        comment="客户端应用ID",
    )
    channel_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("pay_channel.id", ondelete="RESTRICT"),
        nullable=False,
        comment="支付渠道ID",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        comment="当前客户端是否可用",
    )
