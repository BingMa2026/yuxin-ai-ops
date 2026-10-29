from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.dependencies import AuthPermission, db_getter
from app.core.exceptions import CustomException

from .schema import OperationsOverviewSchema
from .service import OperationsOverviewService, resolve_overview_range

OperationsOverviewRouter = APIRouter(prefix="/overview", tags=["运营经营总览"])


@OperationsOverviewRouter.get(
    "",
    response_model=ResponseSchema[OperationsOverviewSchema],
    summary="查询当前客户端经营总览",
)
async def get_operations_overview(
    auth: Annotated[
        AuthSchema,
        Security(AuthPermission(["workspace:operations:overview:list"])),
    ],
    db: Annotated[AsyncSession, Depends(db_getter)],
    preset: Annotated[str, Query()] = "last_30_days",
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    grain: Annotated[str | None, Query()] = None,
    period_days: Annotated[int | None, Query()] = None,
) -> JSONResponse:
    if period_days is not None:
        if period_days not in {7, 30, 90}:
            raise CustomException(msg="兼容统计周期仅支持7天、30天或90天", status_code=422)
        preset = f"last_{period_days}_days"
    query = resolve_overview_range(
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        grain=grain,
    )
    return SuccessResponse(
        data=await OperationsOverviewService(auth, db).overview(query),
        msg="经营总览查询成功",
    )
