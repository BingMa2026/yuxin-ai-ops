from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PageResultSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import (
    ClientUserActivitySchema,
    ClientUserAdminUpdateSchema,
    ClientUserOutSchema,
    ClientUserQueryParam,
    ClientUserStatusSchema,
    ClientUserTagCreateSchema,
    ClientUserTagOutSchema,
    TemporaryPasswordOutSchema,
    UserLevelConfigOutSchema,
    UserLevelConfigSchema,
    UserSegmentCreateSchema,
    UserSegmentOutSchema,
)
from .service import ClientUserService, UserLevelService, UserSegmentService

ClientUserAdminRouter = APIRouter(route_class=OperationLogRoute, prefix="/client-users", tags=["客户端用户管理"])
ClientUserRuleRouter = APIRouter(route_class=OperationLogRoute, prefix="/client-user-operations", tags=["客户端用户规则"])


@ClientUserAdminRouter.get("/list", response_model=ResponseSchema[PageResultSchema[ClientUserOutSchema]], summary="客户端用户列表")
async def list_client_users(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[ClientUserQueryParam, Query()],
) -> JSONResponse:
    return SuccessResponse(
        data=await ClientUserService(auth, db).page(page.page_no, page.page_size, search),
        msg="查询客户端用户成功",
    )


@ClientUserAdminRouter.get("/{user_id}", response_model=ResponseSchema[ClientUserOutSchema], summary="客户端用户详情")
async def get_client_user(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    user_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(data=await ClientUserService(auth, db).detail(user_id))


@ClientUserAdminRouter.get(
    "/{user_id}/activity",
    response_model=ResponseSchema[ClientUserActivitySchema],
    summary="客户端用户订阅、积分与模型用量",
)
async def get_client_user_activity(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    user_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(data=await ClientUserService(auth, db).activity(user_id))


@ClientUserAdminRouter.patch("/{user_id}", response_model=ResponseSchema[ClientUserOutSchema], summary="修改客户端用户资料")
async def update_client_user(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    user_id: Annotated[int, Path(gt=0)],
    data: Annotated[ClientUserAdminUpdateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ClientUserService(auth, db).update(user_id, data), msg="用户资料更新成功")


@ClientUserAdminRouter.patch("/{user_id}/status", response_model=ResponseSchema[ClientUserOutSchema], summary="启用或停用客户端用户")
async def set_client_user_status(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    user_id: Annotated[int, Path(gt=0)],
    data: Annotated[ClientUserStatusSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ClientUserService(auth, db).set_status(user_id, data), msg="用户状态更新成功")


@ClientUserAdminRouter.post("/{user_id}/temporary-password", response_model=ResponseSchema[TemporaryPasswordOutSchema], summary="生成临时密码")
async def reset_client_user_password(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:reset-password"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    user_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(data=await ClientUserService(auth, db).reset_password(user_id), msg="临时密码已生成")


@ClientUserAdminRouter.post("/{user_id}/tags", response_model=ResponseSchema[ClientUserTagOutSchema], summary="添加人工标签")
async def add_client_user_tag(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    user_id: Annotated[int, Path(gt=0)],
    data: Annotated[ClientUserTagCreateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ClientUserService(auth, db).add_tag(user_id, data), msg="标签添加成功")


@ClientUserAdminRouter.delete("/{user_id}/tags/{tag_id}", response_model=ResponseSchema[None], summary="移除人工标签")
async def remove_client_user_tag(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    user_id: Annotated[int, Path(gt=0)],
    tag_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    await ClientUserService(auth, db).remove_tag(user_id, tag_id)
    return SuccessResponse(msg="标签移除成功")


@ClientUserRuleRouter.get("/levels/config/current", response_model=ResponseSchema[UserLevelConfigOutSchema], summary="用户等级规则")
async def get_level_config(auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:list"]))], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await UserLevelService(auth, db).config())


@ClientUserRuleRouter.put("/levels/config/current", response_model=ResponseSchema[UserLevelConfigOutSchema], summary="保存并重算用户等级")
async def save_level_config(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:update"]))], db: Annotated[AsyncSession, Depends(db_getter)], data: Annotated[UserLevelConfigSchema, Body()]
) -> JSONResponse:
    from app.core.exceptions import CustomException

    raise CustomException(msg="旧LV规则已转为历史只读，请在规则中心维护用户等级和推广等级", status_code=410)


@ClientUserRuleRouter.post("/levels/recalculate", response_model=ResponseSchema[int], summary="立即重算用户等级")
async def recalculate_levels(auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:update"]))], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    from app.core.exceptions import CustomException

    raise CustomException(msg="请在规则中心评估当前等级规则", status_code=410)


@ClientUserRuleRouter.get("/segments/saved", response_model=ResponseSchema[list[UserSegmentOutSchema]], summary="动态用户分群")
async def list_segments(auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:list"]))], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await UserSegmentService(auth, db).list())


@ClientUserRuleRouter.post("/segments/saved", response_model=ResponseSchema[UserSegmentOutSchema], summary="保存动态用户分群")
async def create_segment(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:update"]))], db: Annotated[AsyncSession, Depends(db_getter)], data: Annotated[UserSegmentCreateSchema, Body()]
) -> JSONResponse:
    return SuccessResponse(data=await UserSegmentService(auth, db).create(data), msg="用户分群已保存")
