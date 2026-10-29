from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Security, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import (
    WorkspaceModuleCreateSchema,
    WorkspaceModuleOutSchema,
    WorkspaceModuleQueryParam,
    WorkspaceModuleUpdateSchema,
)
from .service import WorkspaceModuleService

WorkspaceModuleRouter = APIRouter(route_class=OperationLogRoute, prefix="/module", tags=["模块管理"])


@WorkspaceModuleRouter.get("/available", summary="查询当前用户可用模块", response_model=ResponseSchema[list[WorkspaceModuleOutSchema]])
async def get_available_modules_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission())],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    modules = await WorkspaceModuleService(auth, db).available()
    return SuccessResponse(data=modules, msg="查询可用模块成功")


@WorkspaceModuleRouter.get("/list", summary="查询模块列表", response_model=ResponseSchema[list[WorkspaceModuleOutSchema]])
async def get_modules_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_system:module:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    search: Annotated[WorkspaceModuleQueryParam, Query()],
) -> JSONResponse:
    modules = await WorkspaceModuleService(auth, db).list(search=search)
    return SuccessResponse(data=modules, msg="查询模块列表成功")


@WorkspaceModuleRouter.get("/detail/{id}", summary="查询模块详情", response_model=ResponseSchema[WorkspaceModuleOutSchema])
async def get_module_detail_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_system:module:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    module = await WorkspaceModuleService(auth, db).detail(id=id)
    return SuccessResponse(data=module, msg="查询模块详情成功")


@WorkspaceModuleRouter.post("/create", status_code=status.HTTP_201_CREATED, summary="创建模块", response_model=ResponseSchema[WorkspaceModuleOutSchema])
async def create_module_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_system:module:add"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[WorkspaceModuleCreateSchema, Body()],
) -> JSONResponse:
    module = await WorkspaceModuleService(auth, db).create(data=data)
    return SuccessResponse(data=module, msg="创建模块成功")


@WorkspaceModuleRouter.put("/update/{id}", summary="修改模块", response_model=ResponseSchema[WorkspaceModuleOutSchema])
async def update_module_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_system:module:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
    data: Annotated[WorkspaceModuleUpdateSchema, Body()],
) -> JSONResponse:
    module = await WorkspaceModuleService(auth, db).update(id=id, data=data)
    return SuccessResponse(data=module, msg="修改模块成功")


@WorkspaceModuleRouter.delete("/delete", summary="删除模块", response_model=ResponseSchema[None])
async def delete_module_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_system:module:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body()],
) -> JSONResponse:
    await WorkspaceModuleService(auth, db).delete(ids=ids)
    return SuccessResponse(msg="删除模块成功")
