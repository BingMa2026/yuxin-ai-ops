from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.client_dependencies import get_current_client_user
from app.core.dependencies import AuthPermission, db_getter

from .schema import (
    TelemetryBatchIn,
    TelemetryBatchOut,
    TelemetryDiagnosticsOut,
    TelemetryEventDiagnosticOut,
)
from .service import TelemetryService

TelemetryClientRouter = APIRouter(tags=["客户端运营遥测"])
TelemetryOperationsRouter = APIRouter(prefix="/telemetry", tags=["客户端遥测诊断"])


@TelemetryClientRouter.post("/events:batch", response_model=ResponseSchema[TelemetryBatchOut])
async def ingest_telemetry_events(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[TelemetryBatchIn, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await TelemetryService(auth, db).ingest(data))


@TelemetryOperationsRouter.get("/diagnostics", response_model=ResponseSchema[TelemetryDiagnosticsOut])
async def telemetry_diagnostics(
    auth: Annotated[
        AuthSchema,
        Security(AuthPermission(["workspace:operations:overview:list"])),
    ],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    return SuccessResponse(data=await TelemetryService(auth, db).diagnostics())


@TelemetryOperationsRouter.get(
    "/events/{event_id}", response_model=ResponseSchema[TelemetryEventDiagnosticOut]
)
async def telemetry_event_diagnostic(
    auth: Annotated[
        AuthSchema,
        Security(AuthPermission(["workspace:operations:overview:list"])),
    ],
    db: Annotated[AsyncSession, Depends(db_getter)],
    event_id: Annotated[str, Path(min_length=8, max_length=64)],
) -> JSONResponse:
    return SuccessResponse(data=await TelemetryService(auth, db).event_diagnostic(event_id))
