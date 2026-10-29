"""Startup must preserve menus maintained by operators, using isolated SQLite."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.module_system.menu.model import MenuModel
from app.api.v1.module_system.role.model import RoleMenusModel
from app.api.v1.module_system.workspace.model import WorkspaceModuleModel
from app.core.base_model import MappedBase
from app.scripts import initialize


@pytest.fixture
async def isolated_sessions(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(MappedBase.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(initialize, "async_db_session", sessions)
    monkeypatch.setattr(initialize, "check_db", AsyncMock())
    monkeypatch.setattr(initialize, "create_tables", AsyncMock())
    try:
        yield sessions
    finally:
        await engine.dispose()


async def navigation_snapshot(sessions):
    async with sessions() as db:
        return {
            model.__tablename__: [dict(row) for row in (await db.execute(select(model.__table__).order_by(*model.__table__.primary_key.columns))).mappings()]
            for model in (MenuModel, WorkspaceModuleModel, RoleMenusModel)
        }


async def test_fresh_database_gets_default_navigation_once(isolated_sessions):
    await initialize.InitializeData().init_db()
    async with isolated_sessions() as db:
        roots = list(await db.scalars(select(MenuModel).where(MenuModel.parent_id.is_(None), MenuModel.scope == "web")))
        assert roots and all(root.module_id is not None for root in roots)
        model_menu = await db.scalar(select(MenuModel).where(MenuModel.route_name == "ModelManagement"))
        assert model_menu.component_path == "module_model_gateway/management/index"
        assert await db.scalar(select(MenuModel.id).where(MenuModel.permission == "workspace:resource:model:edit"))
    before = await navigation_snapshot(isolated_sessions)
    await initialize.InitializeData().init_db()
    assert await navigation_snapshot(isolated_sessions) == before


@pytest.mark.parametrize("soft_delete", [False, True])
async def test_restart_preserves_deleted_moved_and_customized_menus(isolated_sessions, soft_delete):
    await initialize.InitializeData().init_db()
    async with isolated_sessions() as db, db.begin():
        root = await db.scalar(select(MenuModel).where(MenuModel.route_name == "ResourceCenter"))
        target = await db.scalar(select(MenuModel).where(MenuModel.route_name == "RuleEngine"))
        module = await db.scalar(select(WorkspaceModuleModel).where(WorkspaceModuleModel.code == "finance"))
        root.module_id = module.id
        root.name = root.title = "自定义资源"
        root.order = 987
        root.hidden = True
        root.redirect = "/custom"
        module.name = "自定义财务"
        module.description = "运营维护的说明"
        module.icon = "ri:settings-line"
        module.accent = "purple"
        moved = await db.scalar(select(MenuModel).where(MenuModel.route_name == "ClientModelConfiguration"))
        moved.parent_id = target.id
        moved.route_path = "custom-models"
        moved.name = moved.title = "自定义模型"
        moved.order = 888
        moved.hidden = True
        deleted = await db.scalar(select(MenuModel).where(MenuModel.route_name == "ModelManagement"))
        deleted_ids = [deleted.id, *list(await db.scalars(select(MenuModel.id).where(MenuModel.parent_id == deleted.id)))]
        await db.execute(delete(RoleMenusModel).where(RoleMenusModel.menu_id.in_(deleted_ids)))
        if soft_delete:
            for menu in await db.scalars(select(MenuModel).where(MenuModel.id.in_(deleted_ids))):
                menu.is_deleted = True
        else:
            await db.execute(delete(MenuModel).where(MenuModel.parent_id == deleted.id))
            await db.delete(deleted)
        db.add(RoleMenusModel(role_id=1, menu_id=moved.id))
    before = await navigation_snapshot(isolated_sessions)
    for _ in range(2):
        await initialize.InitializeData().init_db()
        assert await navigation_snapshot(isolated_sessions) == before


async def test_existing_installation_with_empty_navigation_is_not_reseeded(isolated_sessions):
    await initialize.InitializeData().init_db()
    async with isolated_sessions() as db, db.begin():
        await db.execute(delete(RoleMenusModel))
        await db.execute(delete(MenuModel))
        await db.execute(delete(WorkspaceModuleModel))
    await initialize.InitializeData().init_db()
    assert await navigation_snapshot(isolated_sessions) == {"sys_menu": [], "sys_module": [], "sys_role_menus": []}
