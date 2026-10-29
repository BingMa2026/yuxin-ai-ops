from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Path, Query, Security, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_client.user.crud import ClientUserCRUD
from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.client_dependencies import get_current_client_user
from app.core.dependencies import AuthPermission, db_getter
from app.core.exceptions import CustomException
from app.core.router_class import OperationLogRoute

from .duration_controller import DurationAdminRouter
from .mode_switch.schema import ModeSwitchPreviewIn, ModeSwitchPreviewOut
from .mode_switch.service import preview_switch
from .schema import (
    CatalogPlanCreateSchema,
    CatalogPlanOutSchema,
    CatalogPlanUpdateSchema,
    ClientCreditLedgerOutSchema,
    ClientSubscriptionOutSchema,
    CreditAccountOutSchema,
    CreditAdjustSchema,
    PricingStrategyCreateSchema,
    PricingStrategyOutSchema,
    PricingStrategyStatusSchema,
    PricingTemplateOutSchema,
    PricingVersionCreateSchema,
    PricingVersionOutSchema,
    PricingVersionUpdateSchema,
    SubscriptionAdminOutSchema,
    SubscriptionStatusSchema,
)
from .service import CatalogService, CreditService, PricingService, SubscriptionService

PricingRouter = APIRouter(route_class=OperationLogRoute, prefix="/pricing", tags=["价格体系"])
CatalogAdminRouter = APIRouter(route_class=OperationLogRoute, prefix="/catalog", tags=["产品刊例"])
ClientBillingRouter = APIRouter(tags=["客户端订阅与积分"])
SubscriptionAdminRouter = APIRouter(prefix="/subscriptions", tags=["订阅与积分"])
SubscriptionAdminRouter.include_router(DurationAdminRouter)



@ClientBillingRouter.post("/mode-switch/preview", response_model=ResponseSchema[ModeSwitchPreviewOut])
async def preview_billing_mode_switch(auth: Annotated[AuthSchema, Depends(get_current_client_user)], db: Annotated[AsyncSession, Depends(db_getter)], data: ModeSwitchPreviewIn):
    return SuccessResponse(data=(await preview_switch(db, auth, data)).model_dump(mode="json"))



@SubscriptionAdminRouter.get("", response_model=ResponseSchema[list[SubscriptionAdminOutSchema]])
async def list_subscriptions(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:subscription:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    entitlement_kind: Literal["credits", "duration"] | None = None,
) -> JSONResponse:
    if not auth.app_id:
        raise CustomException(msg="请先选择客户端", status_code=409)
    await CreditService(db).release_due(app_id=auth.app_id)
    return SuccessResponse(data=await SubscriptionService(db).list_admin(auth.app_id, entitlement_kind=entitlement_kind))


@SubscriptionAdminRouter.patch("/{subscription_id}/status", response_model=ResponseSchema[SubscriptionAdminOutSchema])
async def set_subscription_status(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:subscription:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    subscription_id: Annotated[int, Path(gt=0)],
    data: Annotated[SubscriptionStatusSchema, Body()],
) -> JSONResponse:
    if not auth.app_id:
        raise CustomException(msg="请先选择客户端", status_code=409)
    result = await SubscriptionService(db).set_status(auth.app_id, subscription_id, data)
    return SuccessResponse(data=result, msg=f"订阅状态已修正：{data.reason}")


@PricingRouter.get("/versions", response_model=ResponseSchema[list[PricingVersionOutSchema]])
async def list_pricing_versions(auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:price:list"]))], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await PricingService(auth, db).versions())


@PricingRouter.get("/preview", response_model=ResponseSchema[list[CatalogPlanOutSchema]])
async def preview_current_pricing(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:price:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    user_id: Annotated[int | None, Query(gt=0)] = None,
    purchase_type: Literal["first", "renewal"] = "first",
) -> JSONResponse:
    return SuccessResponse(data=await CatalogService(auth, db).list_plans(public_only=True, purchase_type=purchase_type, user_id=user_id))


@PricingRouter.post("/versions", response_model=ResponseSchema[PricingVersionOutSchema], status_code=status.HTTP_201_CREATED)
async def create_pricing_version(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:price:create"]))], db: Annotated[AsyncSession, Depends(db_getter)], data: Annotated[PricingVersionCreateSchema, Body()]
) -> JSONResponse:
    return SuccessResponse(data=await PricingService(auth, db).create_version(data), msg="价格体系版本创建成功", status_code=status.HTTP_201_CREATED)


@PricingRouter.put("/versions/{version_id}", response_model=ResponseSchema[PricingVersionOutSchema])
async def update_pricing_version(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:price:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    version_id: Annotated[int, Path(gt=0)],
    data: Annotated[PricingVersionUpdateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(
        data=await PricingService(auth, db).update_version(version_id, data),
        msg="价格体系已更新",
    )


@PricingRouter.delete("/versions/{version_id}")
async def delete_pricing_version(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:price:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    version_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    await PricingService(auth, db).delete_version(version_id)
    return SuccessResponse(msg="价格体系已删除")


@PricingRouter.get("/versions/{version_id}/templates", response_model=ResponseSchema[list[PricingTemplateOutSchema]])
async def list_pricing_templates(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:price:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    version_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(data=await PricingService(auth, db).templates(version_id))


@PricingRouter.post("/versions/{version_id}/publish", response_model=ResponseSchema[PricingVersionOutSchema])
async def publish_pricing_version(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:price:publish"]))], db: Annotated[AsyncSession, Depends(db_getter)], version_id: Annotated[int, Path(gt=0)]
) -> JSONResponse:
    return SuccessResponse(data=await PricingService(auth, db).publish(version_id), msg="价格体系已发布")


@CatalogAdminRouter.get("/plans", response_model=ResponseSchema[list[CatalogPlanOutSchema]])
async def list_catalog_plans(auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:rate-card:list"]))], db: Annotated[AsyncSession, Depends(db_getter)], entitlement_kind: Literal["credits", "duration"] | None = None) -> JSONResponse:
    return SuccessResponse(data=await CatalogService(auth, db).list_plans(entitlement_kind=entitlement_kind))


@CatalogAdminRouter.post("/plans", response_model=ResponseSchema[CatalogPlanOutSchema], status_code=status.HTTP_201_CREATED)
async def create_catalog_plan(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:rate-card:create"]))], db: Annotated[AsyncSession, Depends(db_getter)], data: Annotated[CatalogPlanCreateSchema, Body()]
) -> JSONResponse:
    return SuccessResponse(data=await CatalogService(auth, db).create(data), msg="刊例创建成功", status_code=status.HTTP_201_CREATED)


@CatalogAdminRouter.patch("/plans/{plan_id}", response_model=ResponseSchema[CatalogPlanOutSchema])
async def update_catalog_plan(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:rate-card:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    plan_id: Annotated[int, Path(gt=0)],
    data: Annotated[CatalogPlanUpdateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await CatalogService(auth, db).update(plan_id, data), msg="刊例更新成功")


@CatalogAdminRouter.get("/strategies", response_model=ResponseSchema[list[PricingStrategyOutSchema]])
async def list_pricing_strategies(auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:pricing:list"]))], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await CatalogService(auth, db).strategies())


@CatalogAdminRouter.post("/strategies", response_model=ResponseSchema[PricingStrategyOutSchema], status_code=status.HTTP_201_CREATED)
async def create_pricing_strategy(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:pricing:create"]))], db: Annotated[AsyncSession, Depends(db_getter)], data: Annotated[PricingStrategyCreateSchema, Body()]
) -> JSONResponse:
    return SuccessResponse(data=await CatalogService(auth, db).create_strategy(data), msg="定价策略创建成功", status_code=status.HTTP_201_CREATED)


@CatalogAdminRouter.get("/strategies/{strategy_id}", response_model=ResponseSchema[PricingStrategyOutSchema])
async def get_pricing_strategy(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:pricing:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    strategy_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(data=await CatalogService(auth, db).strategy(strategy_id))


@CatalogAdminRouter.put("/strategies/{strategy_id}", response_model=ResponseSchema[PricingStrategyOutSchema])
async def update_pricing_strategy(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:pricing:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    strategy_id: Annotated[int, Path(gt=0)],
    data: Annotated[PricingStrategyCreateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await CatalogService(auth, db).update_strategy(strategy_id, data), msg="定价策略更新成功")


@CatalogAdminRouter.delete("/strategies/{strategy_id}")
async def delete_pricing_strategy(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:pricing:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    strategy_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    await CatalogService(auth, db).delete_strategy(strategy_id)
    return SuccessResponse(msg="定价策略已删除")


@CatalogAdminRouter.patch("/strategies/{strategy_id}/status", response_model=ResponseSchema[PricingStrategyOutSchema])
async def set_pricing_strategy_status(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:pricing:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    strategy_id: Annotated[int, Path(gt=0)],
    data: Annotated[PricingStrategyStatusSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(
        data=await CatalogService(auth, db).set_strategy_status(strategy_id, data),
        msg="定价策略状态已更新",
    )


@CatalogAdminRouter.post("/users/{user_id}/credits", response_model=ResponseSchema[CreditAccountOutSchema])
async def adjust_user_credits(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:credits"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    user_id: Annotated[int, Path(gt=0)],
    data: Annotated[CreditAdjustSchema, Body()],
) -> JSONResponse:
    if not auth.app_id:
        raise CustomException(msg="请先选择客户端", status_code=409)
    await ClientUserCRUD(auth, db).get_or_404(id=user_id, msg="客户端用户不存在")
    result = await CreditService(db).adjust(auth.app_id, user_id, data.amount, data.reason, auth.user.id, data.expires_in_days, data.idempotency_key)
    return SuccessResponse(data=result, msg="积分调整成功")


@ClientBillingRouter.get("/catalog", response_model=ResponseSchema[list[CatalogPlanOutSchema]])
async def get_client_catalog(auth: Annotated[AuthSchema, Depends(get_current_client_user)], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await CatalogService(auth, db).list_plans(public_only=True))


@ClientBillingRouter.get("/account", response_model=ResponseSchema[CreditAccountOutSchema])
async def get_client_credit_account(auth: Annotated[AuthSchema, Depends(get_current_client_user)], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await CreditService(db).account_out(auth.app_id or 0, auth.user.id))


@ClientBillingRouter.get(
    "/subscription",
    response_model=ResponseSchema[ClientSubscriptionOutSchema | None],
)
async def get_client_subscription(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    return SuccessResponse(
        data=await SubscriptionService(db).current_for_client(
            auth.app_id or 0,
            auth.user.id,
        )
    )


@ClientBillingRouter.get(
    "/ledger",
    response_model=ResponseSchema[list[ClientCreditLedgerOutSchema]],
)
async def get_client_credit_ledger(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    await CreditService(db).release_due(app_id=auth.app_id or 0, user_id=auth.user.id)
    return SuccessResponse(
        data=await SubscriptionService(db).ledger_for_client(
            auth.app_id or 0,
            auth.user.id,
        )
    )
