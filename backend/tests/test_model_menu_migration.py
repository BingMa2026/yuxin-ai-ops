"""Menu split preserves existing role access, without a live database."""

import importlib
from unittest.mock import patch

import sqlalchemy as sa


def test_model_menu_split_is_idempotent_and_preserves_grants():
    migration = importlib.import_module("app.alembic.versions.20260907_model_menus")
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    menu = sa.Table(
        "sys_menu",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        *[sa.Column(key, sa.String) for key in ("uuid", "name", "title", "route_name", "route_path", "component_path", "icon", "description", "permission")],
        sa.Column("is_deleted", sa.Boolean),
        sa.Column("order", sa.Integer),
        sa.Column("parent_id", sa.Integer),
        sa.Column("created_time", sa.DateTime),
        sa.Column("updated_time", sa.DateTime),
    )
    grants = sa.Table("sys_role_menus", metadata, sa.Column("role_id", sa.Integer, primary_key=True), sa.Column("menu_id", sa.Integer, primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as db:
        db.execute(
            menu.insert().values(
                id=1,
                uuid="original",
                name="模型管理",
                title="模型管理",
                route_name="ModelManagement",
                route_path="model-management",
                component_path="module_model_gateway/management/index",
                is_deleted=False,
                parent_id=8,
                permission="workspace:resource:model:list",
                order=1,
            )
        )
        db.execute(grants.insert(), [{"role_id": 4, "menu_id": 1}, {"role_id": 7, "menu_id": 1}])
        with patch.object(migration.op, "get_bind", return_value=db):
            migration.upgrade()
            migration.upgrade()
            rows = db.execute(sa.select(menu).order_by(menu.c.id)).mappings().all()
            assert len(rows) == 2
            assert rows[0]["title"] == "供应商与模型"
            assert rows[0]["route_path"] == "model-management"
            assert rows[1]["component_path"] == "module_model_gateway/client/index"
            assert rows[1]["parent_id"] == rows[0]["parent_id"]
            assert rows[1]["permission"] == rows[0]["permission"]
            assert set(db.execute(sa.select(grants.c.role_id).where(grants.c.menu_id == rows[1]["id"])).scalars()) == {4, 7}
            assert db.scalar(sa.select(sa.func.count()).select_from(grants)) == 4
            migration.downgrade()
            assert db.scalar(sa.select(sa.func.count()).select_from(menu)) == 1
            assert db.scalar(sa.select(menu.c.title)) == "模型管理"
            assert db.scalar(sa.select(sa.func.count()).select_from(grants)) == 2
    engine.dispose()
