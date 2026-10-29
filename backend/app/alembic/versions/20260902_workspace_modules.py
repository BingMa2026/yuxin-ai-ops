"""运营平台模块工作台与菜单归属。

Revision ID: 20260902_workspace_modules
Revises:
Create Date: 2026-09-02
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

from app.api.v1.module_system.workspace.seed import MODULE_SEEDS, WORKSPACE_MENU_SEEDS

revision: str = "20260902_workspace_modules"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _menu_values(**values) -> dict:
    now = datetime.now(UTC)
    base = {
        "uuid": str(uuid4()),
        "is_deleted": False,
        "created_time": now,
        "updated_time": now,
        "name": "",
        "type": 2,
        "order": 999,
        "permission": None,
        "icon": None,
        "route_name": None,
        "route_path": None,
        "component_path": None,
        "redirect": None,
        "hidden": False,
        "keep_alive": True,
        "always_show": False,
        "title": None,
        "params": None,
        "affix": False,
        "link": None,
        "is_iframe": False,
        "is_hide_tab": False,
        "active_path": None,
        "show_badge": False,
        "show_text_badge": None,
        "scope": "web",
        "status": 0,
        "description": "运营平台首期初始化",
        "parent_id": None,
        "module_id": None,
    }
    base.update(values)
    return base


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("sys_module"):
        op.create_table(
            "sys_module",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("uuid", sa.String(64), nullable=False, unique=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("code", sa.String(64), nullable=False, unique=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("icon", sa.String(64), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("accent", sa.String(20), nullable=False, server_default="blue"),
            sa.Column("order", sa.Integer(), nullable=False, server_default="999"),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            comment="运营平台工作台模块表",
        )
        op.create_index("ix_sys_module_code", "sys_module", ["code"], unique=True)
        op.create_index("ix_sys_module_order", "sys_module", ["order"], unique=False)
        op.create_index("ix_sys_module_status", "sys_module", ["status"], unique=False)

    inspector = sa.inspect(bind)
    if inspector.has_table("sys_menu") and "module_id" not in _columns(inspector, "sys_menu"):
        with op.batch_alter_table("sys_menu") as batch_op:
            batch_op.add_column(sa.Column("module_id", sa.Integer(), nullable=True, comment="所属工作台模块ID"))
            batch_op.create_index("ix_sys_menu_module_id", ["module_id"], unique=False)
            batch_op.create_foreign_key("fk_sys_menu_module_id", "sys_module", ["module_id"], ["id"], ondelete="RESTRICT")

    metadata = sa.MetaData()
    modules = sa.Table("sys_module", metadata, autoload_with=bind)
    now = datetime.now(UTC)
    for seed in MODULE_SEEDS:
        exists = bind.execute(sa.select(modules.c.id).where(modules.c.code == seed["code"])).scalar_one_or_none()
        if exists is None:
            bind.execute(
                modules.insert().values(
                    uuid=str(uuid4()),
                    is_deleted=False,
                    created_time=now,
                    updated_time=now,
                    **seed,
                )
            )

    inspector = sa.inspect(bind)
    if not inspector.has_table("sys_menu"):
        return

    metadata = sa.MetaData()
    menus = sa.Table("sys_menu", metadata, autoload_with=bind)
    module_ids = dict(bind.execute(sa.select(modules.c.code, modules.c.id)).all())
    bind.execute(
        menus.update()
        .where(
            menus.c.parent_id.is_(None),
            menus.c.scope == "web",
            menus.c.module_id.is_(None),
            menus.c.is_deleted == sa.false(),
        )
        .values(module_id=module_ids["platform"])
    )

    def ensure_menu(parent_id: int | None, values: dict) -> int:
        stmt = sa.select(menus.c.id).where(menus.c.parent_id == parent_id, menus.c.is_deleted == sa.false())
        if values.get("route_path") is not None:
            stmt = stmt.where(menus.c.route_path == values["route_path"])
        elif values.get("permission"):
            stmt = stmt.where(menus.c.permission == values["permission"])
        else:
            stmt = stmt.where(menus.c.name == values["name"])
        existing = bind.execute(stmt).scalar_one_or_none()
        if existing is not None:
            return int(existing)
        result = bind.execute(menus.insert().values(**_menu_values(parent_id=parent_id, **values)))
        return int(result.inserted_primary_key[0])

    for seed in WORKSPACE_MENU_SEEDS:
        root_id = ensure_menu(
            None,
            {
                "name": seed["name"],
                "type": 1,
                "icon": seed["icon"],
                "order": seed["order"],
                "route_name": seed["route_name"],
                "route_path": seed["route_path"],
                "redirect": seed["redirect"],
                "title": seed["name"],
                "always_show": True,
                "module_id": module_ids[seed["module"]],
            },
        )
        for name, route_name, route_path, permission, icon, order in seed["children"]:
            ensure_menu(
                root_id,
                {
                    "name": name,
                    "type": 2,
                    "icon": icon,
                    "order": order,
                    "permission": permission,
                    "route_name": route_name,
                    "route_path": route_path,
                    "component_path": "workspace/placeholder/index",
                    "title": name,
                    "description": "统一模型厂家、凭证、版本、成本与上下架管理" if route_name == "ModelManagement" else "功能建设中",
                },
            )

    system_root_id = bind.execute(sa.select(menus.c.id).where(menus.c.parent_id.is_(None), menus.c.route_path == "/system", menus.c.is_deleted == sa.false())).scalar_one_or_none()
    if system_root_id is not None:
        module_menu_id = ensure_menu(
            int(system_root_id),
            {
                "name": "模块管理",
                "type": 2,
                "icon": "ri:apps-2-line",
                "order": 2,
                "permission": "module_system:module:list",
                "route_name": "WorkspaceModuleManagement",
                "route_path": "module",
                "component_path": "module_system/module/index",
                "title": "模块管理",
            },
        )
        for order, (name, permission) in enumerate(
            (("新增", "module_system:module:add"), ("编辑", "module_system:module:edit"), ("删除", "module_system:module:delete")),
            start=1,
        ):
            ensure_menu(module_menu_id, {"name": name, "type": 3, "order": order, "permission": permission, "title": name})


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("sys_menu") and "module_id" in _columns(inspector, "sys_menu"):
        metadata = sa.MetaData()
        menus = sa.Table("sys_menu", metadata, autoload_with=bind)
        root_paths = [seed["route_path"] for seed in WORKSPACE_MENU_SEEDS]
        # 仅回滚本次迁移实际创建的菜单，避免误删升级前已存在的同路径自定义菜单。
        root_ids = list(
            bind.execute(
                sa.select(menus.c.id).where(
                    menus.c.route_path.in_(root_paths),
                    menus.c.description == "运营平台首期初始化",
                )
            ).scalars()
        )
        system_id = bind.execute(sa.select(menus.c.id).where(menus.c.route_path == "/system")).scalar_one_or_none()
        module_menu_id = None
        if system_id is not None:
            module_menu_id = bind.execute(
                sa.select(menus.c.id).where(
                    menus.c.parent_id == system_id,
                    menus.c.route_path == "module",
                    menus.c.description == "运营平台首期初始化",
                )
            ).scalar_one_or_none()
        delete_roots = root_ids + ([module_menu_id] if module_menu_id is not None else [])
        if delete_roots:
            child_ids = list(bind.execute(sa.select(menus.c.id).where(menus.c.parent_id.in_(delete_roots))).scalars())
            grandchild_ids = list(bind.execute(sa.select(menus.c.id).where(menus.c.parent_id.in_(child_ids))).scalars()) if child_ids else []
            all_ids = [*grandchild_ids, *child_ids, *delete_roots]
            if inspector.has_table("sys_role_menus"):
                role_menus = sa.Table("sys_role_menus", metadata, autoload_with=bind)
                bind.execute(role_menus.delete().where(role_menus.c.menu_id.in_(all_ids)))
            bind.execute(menus.delete().where(menus.c.id.in_(all_ids)))
        bind.execute(menus.update().values(module_id=None))
        foreign_key_name = next(
            (foreign_key.get("name") for foreign_key in inspector.get_foreign_keys("sys_menu") if foreign_key.get("constrained_columns") == ["module_id"] and foreign_key.get("name")),
            None,
        )
        module_index_exists = any(index.get("name") == "ix_sys_menu_module_id" for index in inspector.get_indexes("sys_menu"))
        with op.batch_alter_table("sys_menu") as batch_op:
            if foreign_key_name:
                batch_op.drop_constraint(foreign_key_name, type_="foreignkey")
            if module_index_exists:
                batch_op.drop_index("ix_sys_menu_module_id")
            batch_op.drop_column("module_id")
    inspector = sa.inspect(bind)
    if inspector.has_table("sys_module"):
        op.drop_table("sys_module")
