from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_system.workspace.crud import WorkspaceModuleCRUD
from app.core.base_schema import AuthSchema, BatchSetAvailable
from app.core.exceptions import CustomException
from app.utils.common_util import (
    get_child_id_map,
    get_child_recursion,
    get_parent_id_map,
    get_parent_recursion,
    search_to_dict,
    traversal_to_tree,
)

from .crud import MenuCRUD
from .schema import (
    MenuCreateSchema,
    MenuOutSchema,
    MenuQueryParam,
    MenuUpdateSchema,
)


class MenuService:
    """菜单管理服务（查询操作租户可见，写操作仅超级管理员可操作）"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def _validate_parent_child_type(self, parent_id: int | None, child_type: int | None) -> None:
        if parent_id is None:
            if child_type is None:
                return
            if child_type not in (1, 2, 4):
                raise CustomException(msg="顶级菜单仅允许目录、菜单或外链类型")
            return
        parent = await MenuCRUD(self.auth, self.db).get(id=parent_id)
        if not parent:
            raise CustomException(msg="父级菜单不存在")
        pt = parent.type
        if pt == 1:
            if child_type not in (1, 2, 4):
                raise CustomException(msg="目录下仅允许新增目录、菜单或外链")
        elif pt == 2:
            if child_type != 3:
                raise CustomException(msg="菜单下仅允许新增按钮")
        else:
            raise CustomException(msg="菜单或链接类型下不允许新增子菜单")

    async def _validate_parent_child_scope(self, parent_id: int | None, scope: str | None) -> None:
        if parent_id is None or scope is None:
            return
        parent = await MenuCRUD(self.auth, self.db).get(id=parent_id)
        if not parent:
            return
        p_scope = getattr(parent, "scope", None) or "web"
        if p_scope != scope:
            raise CustomException(msg="子菜单可见范围须与父菜单一致")

    async def _validate_module_assignment(
        self,
        parent_id: int | None,
        scope: str,
        menu_type: int,
        module_id: int | None,
    ) -> None:
        """仅Web顶级菜单直接归属模块，子菜单和按钮一律继承。"""
        if scope != "web":
            if module_id is not None:
                raise CustomException(msg="移动端菜单不能设置所属模块")
            return
        if parent_id is not None:
            if module_id is not None:
                raise CustomException(msg="子菜单不能单独设置所属模块，将自动继承顶级菜单")
            return
        if menu_type not in (1, 2, 4):
            if module_id is not None:
                raise CustomException(msg="按钮权限不能设置所属模块")
            return
        if module_id is None:
            raise CustomException(msg="Web端顶级菜单必须选择所属模块")
        module = await WorkspaceModuleCRUD(self.auth, self.db).get(id=module_id)
        if not module or module.status == "disabled":
            raise CustomException(msg="所属模块不存在或已禁用")

    async def detail(self, id: int) -> MenuOutSchema:
        menu = await MenuCRUD(self.auth, self.db).get(id=id, preload=["roles"])
        if not menu:
            raise CustomException(msg="菜单不存在")
        menu_out = MenuOutSchema.model_validate(menu)
        if menu.parent_id:
            parent = await MenuCRUD(self.auth, self.db).get(id=menu.parent_id)
            if parent:
                menu_out.parent_name = parent.name
        return menu_out

    async def tree(
        self,
        search: MenuQueryParam | None = None,
        order_by: list[dict] | None = None,
    ) -> list[dict]:
        menu_list = await MenuCRUD(self.auth, self.db).get_list(search=search_to_dict(search), order_by=order_by)
        menu_dict_list = [MenuOutSchema.model_validate(menu).model_dump() for menu in menu_list]
        return traversal_to_tree(menu_dict_list)

    async def create(self, data: MenuCreateSchema) -> MenuOutSchema:
        search: dict[str, Any] = {}
        if data.title is not None:
            search["title"] = data.title
            if data.parent_id is not None:
                search["parent_id"] = data.parent_id
            menu = await MenuCRUD(self.auth, self.db).get(**search)
            if menu:
                raise CustomException(msg="创建失败，该菜单已存在")

        await self._validate_parent_child_type(data.parent_id, data.type)
        await self._validate_parent_child_scope(data.parent_id, data.scope)
        await self._validate_module_assignment(data.parent_id, data.scope, data.type, data.module_id)

        new_menu = await MenuCRUD(self.auth, self.db).create(data=data)
        return MenuOutSchema.model_validate(new_menu)

    async def update(self, id: int, data: MenuUpdateSchema) -> MenuOutSchema:
        current = await MenuCRUD(self.auth, self.db).get_or_404(id=id, msg="更新失败，该菜单不存在")
        fields_set = data.model_fields_set
        effective_parent_id = data.parent_id if "parent_id" in fields_set else current.parent_id
        effective_type = data.type if data.type is not None else current.type
        effective_scope = data.scope if data.scope is not None else current.scope
        effective_module_id = data.module_id if "module_id" in fields_set else current.module_id
        if effective_parent_id is not None:
            effective_module_id = None

        await self._validate_parent_child_type(effective_parent_id, effective_type)
        await self._validate_parent_child_scope(effective_parent_id, effective_scope)
        await self._validate_module_assignment(effective_parent_id, effective_scope, effective_type, effective_module_id)
        if data.title is not None:
            search: dict[str, Any] = {"title": data.title}
            if data.parent_id is not None:
                search["parent_id"] = data.parent_id
            exist_menu = await MenuCRUD(self.auth, self.db).get(**search)
            if exist_menu and exist_menu.id != id:
                raise CustomException(msg="更新失败，菜单标题重复")

        if data.parent_id:
            parent_menu = await MenuCRUD(self.auth, self.db).get(id=data.parent_id)
            if not parent_menu:
                raise CustomException(msg="更新失败，父级菜单不存在")

        update_data = data.model_dump(exclude_unset=True)
        update_data["module_id"] = effective_module_id
        new_menu = await MenuCRUD(self.auth, self.db).update(id=id, data=update_data)

        if data.status is not None:
            await self.set_available(data=BatchSetAvailable(ids=[id], status=data.status))

        menu_out = MenuOutSchema.model_validate(new_menu)
        if menu_out.parent_id:
            parent = await MenuCRUD(self.auth, self.db).get(id=menu_out.parent_id)
            if parent:
                menu_out.parent_name = parent.name
        return menu_out

    async def delete(self, ids: list[int]) -> None:
        if not ids:
            raise CustomException(msg="删除失败，删除对象不能为空")

        all_menus = await MenuCRUD(self.auth, self.db).get_list()
        child_id_map = get_child_id_map(model_list=all_menus)

        delete_ids_set = set()
        for mid in ids:
            all_descendants = get_child_recursion(id=mid, id_map=child_id_map)
            delete_ids_set.update(all_descendants)

        delete_ids = list(delete_ids_set)
        await MenuCRUD(self.auth, self.db).delete(ids=delete_ids)

    async def set_available(self, data: BatchSetAvailable) -> None:
        menu_list = await MenuCRUD(self.auth, self.db).get_list()
        total_ids = []

        if data.status == 0:
            id_map = get_parent_id_map(model_list=menu_list)
            for menu_id in data.ids:
                enable_ids = get_parent_recursion(id=menu_id, id_map=id_map)
                total_ids.extend(enable_ids)
        else:
            id_map = get_child_id_map(model_list=menu_list)
            for menu_id in data.ids:
                disable_ids = get_child_recursion(id=menu_id, id_map=id_map)
                total_ids.extend(disable_ids)

        await MenuCRUD(self.auth, self.db).set(ids=total_ids, status=data.status)
