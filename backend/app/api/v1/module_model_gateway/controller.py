from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Security, status
from fastapi.responses import JSONResponse, StreamingResponse
from redis.asyncio.client import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.client_dependencies import get_current_client_user, get_current_runtime_user
from app.core.dependencies import AuthPermission, db_getter, redis_getter
from app.core.security import OAuth2Schema

from .finance_service import ModelFinanceService
from .gateway import ModelGatewayService
from .request_receipts import ModelRequestReceiptService
from .schema import (
    AppModelBindingCreate,
    AppModelBindingOut,
    AppModelBindingUpdate,
    AppModelRouteCreate,
    AppModelRouteOut,
    ClientModelConfig,
    ClientModelRequestReceipt,
    CustomProviderTemplateCreate,
    DiscoveredModelOut,
    FinanceProfileOut,
    FinanceProfileUpsert,
    FinanceSummaryOut,
    FinanceSyncRequest,
    ManualBillImport,
    ModelCatalogCreate,
    ModelCatalogOut,
    ModelCatalogUpdate,
    ProviderAccountCreate,
    ProviderAccountOut,
    ProviderAccountUpdate,
    ProviderBillOut,
    ProviderConnectionTest,
    ProviderTemplateOut,
    PurchasePriceCreate,
    PurchasePriceOut,
    ResourceStatusUpdate,
    RuntimeCompletionOut,
    RuntimeCompletionRequest,
    RuntimeTokenOut,
)
from .service import ClientModelService, ModelAdminService

ModelAdminRouter = APIRouter(tags=["模型资源管理"])
ModelClientRouter = APIRouter(tags=["客户端模型配置"])
RuntimeRouter = APIRouter(prefix="/runtime", tags=["客户端运行令牌"])


@ModelAdminRouter.get("/provider-templates", response_model=ResponseSchema[list[ProviderTemplateOut]])
async def provider_templates(auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:list"]))], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db).templates())


@ModelAdminRouter.post("/provider-templates", response_model=ResponseSchema[ProviderTemplateOut], status_code=status.HTTP_201_CREATED)
async def create_provider_template(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))], db: Annotated[AsyncSession, Depends(db_getter)], data: Annotated[CustomProviderTemplateCreate, Body()]
) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db).create_custom_template(data), status_code=status.HTTP_201_CREATED)


@ModelAdminRouter.get("/provider-accounts", response_model=ResponseSchema[list[ProviderAccountOut]])
async def provider_accounts(auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:list"]))], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db).accounts())


@ModelAdminRouter.get(
    "/provider-accounts/{account_id}/finance",
    response_model=ResponseSchema[FinanceSummaryOut],
)
async def provider_finance_summary(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    account_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(data=await ModelFinanceService(auth, db).summary(account_id))


@ModelAdminRouter.put(
    "/provider-accounts/{account_id}/finance",
    response_model=ResponseSchema[FinanceProfileOut],
)
async def upsert_provider_finance(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    account_id: Annotated[int, Path(gt=0)],
    data: Annotated[FinanceProfileUpsert, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ModelFinanceService(auth, db).upsert_profile(account_id, data))


@ModelAdminRouter.post(
    "/provider-accounts/{account_id}/finance/sync",
    response_model=ResponseSchema[FinanceSummaryOut],
)
async def sync_provider_finance(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    account_id: Annotated[int, Path(gt=0)],
    data: Annotated[FinanceSyncRequest, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ModelFinanceService(auth, db).sync(account_id, data))


@ModelAdminRouter.post(
    "/provider-accounts/{account_id}/finance/test",
    response_model=ResponseSchema[FinanceProfileOut],
)
async def test_provider_finance(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    account_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(data=await ModelFinanceService(auth, db).test_connection(account_id))


@ModelAdminRouter.post(
    "/provider-accounts/{account_id}/finance/bills:import",
    response_model=ResponseSchema[list[ProviderBillOut]],
)
async def import_provider_bills(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    account_id: Annotated[int, Path(gt=0)],
    data: Annotated[ManualBillImport, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ModelFinanceService(auth, db).import_bills(account_id, data))


@ModelAdminRouter.get(
    "/provider-accounts/{account_id}/prices",
    response_model=ResponseSchema[list[PurchasePriceOut]],
)
async def provider_prices(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    account_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(data=await ModelFinanceService(auth, db).prices(account_id))


@ModelAdminRouter.post(
    "/provider-accounts/{account_id}/prices",
    response_model=ResponseSchema[PurchasePriceOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_provider_price(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    account_id: Annotated[int, Path(gt=0)],
    data: Annotated[PurchasePriceCreate, Body()],
) -> JSONResponse:
    return SuccessResponse(
        data=await ModelFinanceService(auth, db).create_price(account_id, data),
        status_code=status.HTTP_201_CREATED,
    )


@ModelAdminRouter.post("/provider-accounts", response_model=ResponseSchema[ProviderAccountOut], status_code=status.HTTP_201_CREATED)
async def create_provider_account(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))], db: Annotated[AsyncSession, Depends(db_getter)], data: Annotated[ProviderAccountCreate, Body()]
) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db).create_account(data), status_code=status.HTTP_201_CREATED)


@ModelAdminRouter.put("/provider-accounts/{account_id}", response_model=ResponseSchema[ProviderAccountOut])
async def update_provider_account(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    account_id: Annotated[int, Path(gt=0)],
    data: Annotated[ProviderAccountUpdate, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db, redis).update_account(account_id, data), msg="供应商账号已更新，请重新测试连接")


@ModelAdminRouter.post("/provider-accounts/{account_id}/test", response_model=ResponseSchema[ProviderAccountOut])
async def test_provider_account(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))], db: Annotated[AsyncSession, Depends(db_getter)], account_id: Annotated[int, Path(gt=0)]
) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db).test_account(account_id), msg="连接测试成功")


@ModelAdminRouter.post("/provider-accounts/test-connection", response_model=ResponseSchema[list[DiscoveredModelOut]])
async def test_provider_connection(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[ProviderConnectionTest, Body()],
) -> JSONResponse:
    return SuccessResponse(
        data=await ModelAdminService(auth, db).test_connection(data),
        msg="连接测试成功",
    )


@ModelAdminRouter.post("/provider-accounts/{account_id}/discover", response_model=ResponseSchema[list[DiscoveredModelOut]])
async def discover_provider_models(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    account_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(
        data=await ModelAdminService(auth, db).discover_models(account_id, sync=True),
        msg="已刷新并同步供应商模型",
    )


@ModelAdminRouter.patch("/provider-accounts/{account_id}/status", response_model=ResponseSchema[ProviderAccountOut])
async def set_provider_account_status(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    account_id: Annotated[int, Path(gt=0)],
    data: Annotated[ResourceStatusUpdate, Body()],
    redis: Annotated[Redis, Depends(redis_getter)],
) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db, redis).set_account_status(account_id, data))


@ModelAdminRouter.get("/catalog", response_model=ResponseSchema[list[ModelCatalogOut]])
async def model_catalog(auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:list"]))], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db).models())


@ModelAdminRouter.post("/catalog", response_model=ResponseSchema[ModelCatalogOut], status_code=status.HTTP_201_CREATED)
async def create_model_catalog(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))], db: Annotated[AsyncSession, Depends(db_getter)], data: Annotated[ModelCatalogCreate, Body()]
) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db).create_model(data), status_code=status.HTTP_201_CREATED)


@ModelAdminRouter.put("/catalog/{model_id}", response_model=ResponseSchema[ModelCatalogOut])
async def update_model_catalog(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    model_id: Annotated[int, Path(gt=0)],
    data: Annotated[ModelCatalogUpdate, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db, redis).update_model(model_id, data))


@ModelAdminRouter.patch("/catalog/{model_id}/status", response_model=ResponseSchema[ModelCatalogOut])
async def set_model_catalog_status(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    model_id: Annotated[int, Path(gt=0)],
    data: Annotated[ResourceStatusUpdate, Body()],
    redis: Annotated[Redis, Depends(redis_getter)],
) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db, redis).set_model_status(model_id, data))


@ModelAdminRouter.get("/bindings", response_model=ResponseSchema[list[AppModelBindingOut]])
async def app_model_bindings(auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:list"]))], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db).bindings())


@ModelAdminRouter.post("/bindings", response_model=ResponseSchema[AppModelBindingOut], status_code=status.HTTP_201_CREATED)
async def create_app_model_binding(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[AppModelBindingCreate, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db, redis).create_binding(data), status_code=status.HTTP_201_CREATED)


@ModelAdminRouter.put("/bindings/{binding_id}", response_model=ResponseSchema[AppModelBindingOut])
async def update_app_model_binding(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    binding_id: Annotated[int, Path(gt=0)],
    data: Annotated[AppModelBindingUpdate, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db, redis).update_binding(binding_id, data))


@ModelAdminRouter.patch("/bindings/{binding_id}/status", response_model=ResponseSchema[AppModelBindingOut])
async def set_app_model_binding_status(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    binding_id: Annotated[int, Path(gt=0)],
    data: Annotated[ResourceStatusUpdate, Body()],
    redis: Annotated[Redis, Depends(redis_getter)],
) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db, redis).set_binding_status(binding_id, data))


@ModelAdminRouter.get("/routes", response_model=ResponseSchema[list[AppModelRouteOut]])
async def app_model_routes(auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:list"]))], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db).routes())


@ModelAdminRouter.post("/routes", response_model=ResponseSchema[AppModelRouteOut])
async def save_app_model_route(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[AppModelRouteCreate, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ModelAdminService(auth, db, redis).create_route(data), msg="业务路由保存成功")


@ModelClientRouter.get("/config", response_model=ResponseSchema[ClientModelConfig])
async def client_model_config(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
) -> JSONResponse:
    config = await ClientModelService(auth, db, redis).config()
    # The shared application config cache must never contain a user's identity.
    return SuccessResponse(data=config.model_copy(update={"app_id": auth.app_id, "user_id": auth.user.id}))


@ModelClientRouter.get("/requests/{request_id}/receipt", response_model=ResponseSchema[ClientModelRequestReceipt])
async def client_model_request_receipt(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    request_id: Annotated[str, Path(pattern=r"^[a-zA-Z0-9_.:-]{8,128}$")],
) -> JSONResponse:
    receipt = await ModelRequestReceiptService(auth, db).get(request_id)
    # Keep UTC ISO serialization identical to the canonical receipt hash payload.
    response = SuccessResponse(data=receipt.model_dump(mode="json"))
    response.headers["Cache-Control"] = "no-store"
    return response


@RuntimeRouter.post("/token", response_model=ResponseSchema[RuntimeTokenOut])
async def create_runtime_token(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)], token: Annotated[str, Depends(OAuth2Schema)], db: Annotated[AsyncSession, Depends(db_getter)]
) -> JSONResponse:
    from app.api.v1.module_client.app.model_policy import require_platform_model

    app = await require_platform_model(db, auth.app_id, user_id=auth.user.id)
    from app.api.v1.module_client.app.model_policy import billing_user
    user = await billing_user(db, app, auth.user.id)
    return SuccessResponse(data=ClientModelService.runtime_token(token, mode_version=user.mode_version, policy_version=app.model_policy_version))


@RuntimeRouter.post("/complete", response_model=ResponseSchema[RuntimeCompletionOut])
async def runtime_complete(
    auth: Annotated[AuthSchema, Depends(get_current_runtime_user)],
    data: Annotated[RuntimeCompletionRequest, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ModelGatewayService(auth).complete(data))


@RuntimeRouter.post("/stream")
async def runtime_stream(
    auth: Annotated[AuthSchema, Depends(get_current_runtime_user)],
    data: Annotated[RuntimeCompletionRequest, Body()],
) -> StreamingResponse:
    service = ModelGatewayService(auth)
    prepared = await service.prepare_stream(data)
    return StreamingResponse(
        service.stream(data, prepared),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
