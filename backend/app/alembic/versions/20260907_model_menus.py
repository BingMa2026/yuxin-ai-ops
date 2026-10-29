"""Split supplier models and client configuration into resource menus."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_model_menus"
down_revision: str | None = "20260904_cost_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("sys_menu"):
        return
    metadata = sa.MetaData()
    menu = sa.Table("sys_menu", metadata, autoload_with=bind)
    original = bind.execute(sa.select(menu).where(menu.c.route_name == "ModelManagement", menu.c.is_deleted.is_(False))).mappings().first()
    if original is None:
        return
    bind.execute(menu.update().where(menu.c.id == original["id"]).values(name="供应商与模型", title="供应商与模型", icon="ri:server-line", order=1))
    client_id = bind.execute(sa.select(menu.c.id).where(menu.c.route_name == "ClientModelConfiguration", menu.c.is_deleted.is_(False))).scalar_one_or_none()
    if client_id is None:
        values = dict(original)
        values.pop("id")
        values.update(
            uuid=str(uuid4()),
            name="客户端模型配置",
            title="客户端模型配置",
            route_name="ClientModelConfiguration",
            route_path="client-models",
            component_path="module_model_gateway/client/index",
            icon="ri:settings-3-line",
            order=2,
            description="按当前客户端配置模型授权与业务路由",
            created_time=datetime.now(UTC),
            updated_time=datetime.now(UTC),
        )
        client_id = bind.execute(menu.insert().values(**values).returning(menu.c.id)).scalar_one()
    # Existing roles could already reach this panel through the original tab.
    if inspector.has_table("sys_role_menus"):
        grants = sa.Table("sys_role_menus", metadata, autoload_with=bind)
        role_ids = bind.execute(sa.select(grants.c.role_id).where(grants.c.menu_id == original["id"])).scalars().all()
        for role_id in role_ids:
            exists = bind.execute(sa.select(grants.c.role_id).where(grants.c.role_id == role_id, grants.c.menu_id == client_id)).first()
            if exists is None:
                bind.execute(grants.insert().values(role_id=role_id, menu_id=client_id))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("sys_menu"):
        return
    metadata = sa.MetaData()
    menu = sa.Table("sys_menu", metadata, autoload_with=bind)
    ids = sa.select(menu.c.id).where(menu.c.route_name == "ClientModelConfiguration")
    if inspector.has_table("sys_role_menus"):
        grants = sa.Table("sys_role_menus", metadata, autoload_with=bind)
        bind.execute(grants.delete().where(grants.c.menu_id.in_(ids)))
    bind.execute(menu.delete().where(menu.c.route_name == "ClientModelConfiguration"))
    bind.execute(menu.update().where(menu.c.route_name == "ModelManagement").values(name="模型管理", title="模型管理", icon="ri:brain-line"))
