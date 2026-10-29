"""微信与支付宝渠道管理。

Revision ID: 20260902_payment_channels
Revises: 20260902_workspace_modules
Create Date: 2026-09-02
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_payment_channels"
down_revision: str | None = "20260902_workspace_modules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_values(**values) -> dict:
    now = datetime.now(UTC)
    result = {
        "uuid": str(uuid4()),
        "is_deleted": False,
        "created_time": now,
        "updated_time": now,
        "deleted_time": None,
        "status": 0,
    }
    result.update(values)
    return result


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("pay_channel"):
        op.create_table(
            "pay_channel",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("uuid", sa.String(64), nullable=False, unique=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider", sa.String(20), nullable=False, unique=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("mode", sa.String(20), nullable=False, server_default="production"),
            sa.Column("fee_rate", sa.Numeric(7, 4), nullable=False, server_default="0"),
            sa.Column("settlement_cycle", sa.String(32), nullable=False, server_default="T+1"),
            sa.Column("scenes", sa.JSON(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("order", sa.Integer(), nullable=False, server_default="999"),
            sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
            comment="支付渠道配置表",
        )
        op.create_index("ix_pay_channel_provider", "pay_channel", ["provider"], unique=True)
        op.create_index("ix_pay_channel_status_deleted", "pay_channel", ["status", "is_deleted"], unique=False)
        op.create_index("ix_pay_channel_created_deleted", "pay_channel", ["created_time", "is_deleted"], unique=False)

    metadata = sa.MetaData()
    channels = sa.Table("pay_channel", metadata, autoload_with=bind)
    for values in (
        {
            "provider": "wechat",
            "name": "微信支付",
            "enabled": False,
            "mode": "production",
            "fee_rate": 0.6,
            "settlement_cycle": "T+1",
            "scenes": ["PC收银台", "二维码支付"],
            "description": "微信支付商户平台渠道",
            "order": 1,
        },
        {
            "provider": "alipay",
            "name": "支付宝",
            "enabled": False,
            "mode": "production",
            "fee_rate": 0.6,
            "settlement_cycle": "T+1",
            "scenes": ["PC收银台", "二维码支付"],
            "description": "支付宝开放平台渠道",
            "order": 2,
        },
    ):
        exists = bind.execute(sa.select(channels.c.id).where(channels.c.provider == values["provider"])).scalar_one_or_none()
        if exists is None:
            bind.execute(channels.insert().values(**_base_values(**values)))

    inspector = sa.inspect(bind)
    if not inspector.has_table("sys_menu"):
        return
    menus = sa.Table("sys_menu", metadata, autoload_with=bind)
    finance_id = bind.execute(
        sa.select(menus.c.id).where(
            menus.c.parent_id.is_(None),
            menus.c.route_path == "/finance",
            menus.c.is_deleted == sa.false(),
        )
    ).scalar_one_or_none()
    if finance_id is None:
        return

    payment_id = bind.execute(
        sa.select(menus.c.id).where(
            menus.c.parent_id == finance_id,
            menus.c.route_path == "payment-channels",
            menus.c.is_deleted == sa.false(),
        )
    ).scalar_one_or_none()
    if payment_id is None:
        values = _base_values(
            name="支付渠道",
            type=2,
            order=1,
            permission="module_payment:channel:list",
            icon="ri:secure-payment-line",
            route_name="PaymentChannelManagement",
            route_path="payment-channels",
            component_path="module_payment/channel/index",
            redirect=None,
            hidden=False,
            keep_alive=True,
            always_show=False,
            title="支付渠道",
            params=None,
            affix=False,
            link=None,
            is_iframe=False,
            is_hide_tab=False,
            active_path=None,
            show_badge=False,
            show_text_badge=None,
            scope="web",
            description="支付渠道模块初始化",
            parent_id=finance_id,
            module_id=None,
        )
        payment_id = bind.execute(menus.insert().values(**values)).inserted_primary_key[0]

    edit_exists = bind.execute(
        sa.select(menus.c.id).where(
            menus.c.parent_id == payment_id,
            menus.c.permission == "module_payment:channel:edit",
            menus.c.is_deleted == sa.false(),
        )
    ).scalar_one_or_none()
    if edit_exists is None:
        bind.execute(
            menus.insert().values(
                **_base_values(
                    name="编辑",
                    type=3,
                    order=1,
                    permission="module_payment:channel:edit",
                    icon=None,
                    route_name=None,
                    route_path=None,
                    component_path=None,
                    redirect=None,
                    hidden=False,
                    keep_alive=True,
                    always_show=False,
                    title="编辑",
                    params=None,
                    affix=False,
                    link=None,
                    is_iframe=False,
                    is_hide_tab=False,
                    active_path=None,
                    show_badge=False,
                    show_text_badge=None,
                    scope="web",
                    description="支付渠道模块初始化",
                    parent_id=payment_id,
                    module_id=None,
                )
            )
        )
    bind.execute(menus.update().where(menus.c.id == finance_id).values(redirect="/finance/payment-channels"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("sys_menu"):
        metadata = sa.MetaData()
        menus = sa.Table("sys_menu", metadata, autoload_with=bind)
        ids = list(bind.execute(sa.select(menus.c.id).where(menus.c.description == "支付渠道模块初始化")).scalars())
        if ids and inspector.has_table("sys_role_menus"):
            role_menus = sa.Table("sys_role_menus", metadata, autoload_with=bind)
            bind.execute(role_menus.delete().where(role_menus.c.menu_id.in_(ids)))
        if ids:
            bind.execute(menus.delete().where(menus.c.id.in_(ids)))
    if inspector.has_table("pay_channel"):
        op.drop_table("pay_channel")
