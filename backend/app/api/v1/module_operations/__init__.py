from fastapi import APIRouter

from app.api.v1.module_telemetry.controller import TelemetryOperationsRouter

from .controller import OperationsOverviewRouter

operations_router = APIRouter(prefix="/operations")
operations_router.include_router(OperationsOverviewRouter)
operations_router.include_router(TelemetryOperationsRouter)
