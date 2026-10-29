from fastapi import APIRouter

from .controller import TelemetryClientRouter

telemetry_client_router = APIRouter(prefix="/client/telemetry")
telemetry_client_router.include_router(TelemetryClientRouter)
