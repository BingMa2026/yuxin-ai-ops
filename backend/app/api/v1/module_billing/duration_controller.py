from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Security
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .duration_adjustment import DurationAdjustmentService
from .duration_schema import DurationAdjustmentOut, DurationAdjustSchema, DurationStateOut

DurationAdminRouter = APIRouter(route_class=OperationLogRoute)
DurationOperator = Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:duration"]))]


@DurationAdminRouter.get("/users/{user_id}/duration", response_model=ResponseSchema[DurationStateOut])
async def duration_state(auth: DurationOperator, db: Annotated[AsyncSession, Depends(db_getter)], user_id: Annotated[int, Path(gt=0)]):
    result = await DurationAdjustmentService(db, auth).state(user_id)
    # Preserve timezone and microseconds for the optimistic expiry comparison;
    # the default response datetime formatter is intended for display only.
    return SuccessResponse(data=result.model_dump(mode="json"))


@DurationAdminRouter.post("/users/{user_id}/duration", response_model=ResponseSchema[DurationAdjustmentOut])
async def adjust_duration(auth: DurationOperator, db: Annotated[AsyncSession, Depends(db_getter)], user_id: Annotated[int, Path(gt=0)], data: Annotated[DurationAdjustSchema, Body()]):
    result = await DurationAdjustmentService(db, auth).adjust(user_id, data)
    return SuccessResponse(data=result.model_dump(mode="json"), msg="使用天数已调整，请在客户端刷新权益")
