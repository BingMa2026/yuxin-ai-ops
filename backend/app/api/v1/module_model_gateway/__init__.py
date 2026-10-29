from fastapi import APIRouter

from app.api.v1.module_model_gateway.controller import ModelAdminRouter, ModelClientRouter

model_operations_router = APIRouter(prefix="/operations/models")
model_client_router = APIRouter(prefix="/client/model")
model_operations_router.include_router(ModelAdminRouter)
model_client_router.include_router(ModelClientRouter)
