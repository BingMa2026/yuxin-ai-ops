from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.v1.module_system.menu.model import MenuModel
from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException
from app.utils.common_util import search_to_dict

from .crud import WorkspaceModuleCRUD
from .schema import (
    WorkspaceModuleCreateSchema,
    WorkspaceModuleMenuItem,
    WorkspaceModuleOutSchema,
    WorkspaceModuleQueryParam,
    WorkspaceModuleUpdateSchema,
)


class WorkspaceModuleService:
    """工作台模块管理与当前用户可用模块推导。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def list(
        self,
        search: WorkspaceModuleQueryParam | None = None,
    ) -> list[WorkspaceModuleOutSchema]:
        modules = await WorkspaceModuleCRUD(self.auth, self.db).get_list(
            search=search_to_dict(search),
            order_by=[{"order": "asc"}, {"id": "asc"}],
        )
        return await self._with_menu_summary(modules)

    async def _with_menu_summary(
        self,
        modules,
        granted_ids: set[int] | None = None,
    ) -> list[WorkspaceModuleOutSchema]:
        """补充每个模块的首层可访问菜单摘要，供工作台和管理页直接预览。"""
        if not modules:
            return []

        module_ids = [module.id for module in modules]
        parent = aliased(MenuModel)
        child_stmt = (
            select(
                parent.module_id,
                MenuModel.id,
                MenuModel.name,
                MenuModel.icon,
                MenuModel.route_path,
                MenuModel.order,
            )
            .join(parent, MenuModel.parent_id == parent.id)
            .where(
                parent.module_id.in_(module_ids),
                parent.scope == "web",
                parent.status == 0,
                parent.is_deleted == False,
                MenuModel.type.in_((2, 4)),
                MenuModel.status == 0,
                MenuModel.is_deleted == False,
            )
            .order_by(parent.module_id.asc(), MenuModel.order.asc(), MenuModel.id.asc())
        )
        if granted_ids is not None:
            child_stmt = child_stmt.where(MenuModel.id.in_(granted_ids))

        rows = (await self.db.execute(child_stmt)).all()
        items_by_module: dict[int, list[WorkspaceModuleMenuItem]] = {module_id: [] for module_id in module_ids}
        counts_by_module: dict[int, int] = dict.fromkeys(module_ids, 0)
        for row in rows:
            counts_by_module[row.module_id] += 1
            if len(items_by_module[row.module_id]) < 4:
                items_by_module[row.module_id].append(WorkspaceModuleMenuItem(name=row.name, icon=row.icon, route_path=row.route_path))

        return [
            WorkspaceModuleOutSchema.model_validate(module).model_copy(
                update={
                    "menu_count": counts_by_module[module.id],
                    "menu_items": items_by_module[module.id],
                }
            )
            for module in modules
        ]

    async def available(self) -> list[WorkspaceModuleOutSchema]:
        """由当前用户的菜单权限反推模块；超级管理员返回全部非禁用模块。"""
        crud = WorkspaceModuleCRUD(self.auth, self.db)
        if self.auth.user.is_superuser:
            modules = await crud.get_list(
                search={"status": ("!=", "disabled")},
                order_by=[{"order": "asc"}, {"id": "asc"}],
            )
            return await self._with_menu_summary(modules)

        granted_ids = set(self.auth.menu_ids)
        if not granted_ids:
            return []

        result = await self.db.execute(
            select(MenuModel.id, MenuModel.parent_id, MenuModel.module_id).where(
                MenuModel.scope == "web",
                MenuModel.status == 0,
                MenuModel.is_deleted == False,
            )
        )
        menu_rows = result.all()
        parent_by_id = {row.id: row.parent_id for row in menu_rows}
        module_by_id = {row.id: row.module_id for row in menu_rows}

        available_module_ids: set[int] = set()
        for menu_id in granted_ids:
            cursor: int | None = menu_id
            visited: set[int] = set()
            while cursor and cursor not in visited:
                visited.add(cursor)
                module_id = module_by_id.get(cursor)
                if module_id:
                    available_module_ids.add(module_id)
                    break
                cursor = parent_by_id.get(cursor)

        if not available_module_ids:
            return []
        modules = await crud.get_list(
            search={"id": ("in", list(available_module_ids)), "status": ("!=", "disabled")},
            order_by=[{"order": "asc"}, {"id": "asc"}],
        )
        return await self._with_menu_summary(modules, granted_ids=granted_ids)

    async def detail(self, id: int) -> WorkspaceModuleOutSchema:
        module = await WorkspaceModuleCRUD(self.auth, self.db).get_or_404(id=id, msg="模块不存在")
        return WorkspaceModuleOutSchema.model_validate(module)

    async def create(self, data: WorkspaceModuleCreateSchema) -> WorkspaceModuleOutSchema:
        crud = WorkspaceModuleCRUD(self.auth, self.db)
        if await crud.exists(code=data.code):
            raise CustomException(msg="模块编码已存在")
        module = await crud.create(data=data)
        return WorkspaceModuleOutSchema.model_validate(module)

    async def update(self, id: int, data: WorkspaceModuleUpdateSchema) -> WorkspaceModuleOutSchema:
        crud = WorkspaceModuleCRUD(self.auth, self.db)
        await crud.get_or_404(id=id, msg="更新失败，模块不存在")
        if data.code:
            exists = await crud.get(code=data.code)
            if exists and exists.id != id:
                raise CustomException(msg="模块编码已存在")
        module = await crud.update(id=id, data=data)
        return WorkspaceModuleOutSchema.model_validate(module)

    async def delete(self, ids: list[int]) -> None:
        if not ids:
            raise CustomException(msg="删除对象不能为空")
        menu_count = await self.db.scalar(
            select(func.count(MenuModel.id)).where(
                MenuModel.module_id.in_(ids),
                MenuModel.is_deleted == False,
            )
        )
        if menu_count:
            raise CustomException(msg="所选模块仍有关联菜单，请先调整菜单所属模块")
        await WorkspaceModuleCRUD(self.auth, self.db).delete(ids=ids)
