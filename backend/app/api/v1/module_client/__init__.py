from fastapi import APIRouter

from app.api.v1.module_client.app.controller import ClientAppRouter, ClientUpdatePublicRouter
from app.api.v1.module_client.auth.controller import ClientAuthRouter, ClientSelfRouter
from app.api.v1.module_client.user.controller import ClientUserAdminRouter, ClientUserRuleRouter
from app.api.v1.module_model_gateway.controller import RuntimeRouter

from .runtime_config import ClientRuntimeConfigRouter

operations_client_router = APIRouter(prefix="/operations")
operations_client_router.include_router(ClientAppRouter)
operations_client_router.include_router(ClientUserAdminRouter)
operations_client_router.include_router(ClientUserRuleRouter)

client_public_router = APIRouter(prefix="/client")
client_public_router.include_router(ClientRuntimeConfigRouter)
client_public_router.include_router(ClientAuthRouter)
client_public_router.include_router(ClientSelfRouter)
client_public_router.include_router(RuntimeRouter)

client_update_public_router = APIRouter()
client_update_public_router.include_router(ClientUpdatePublicRouter)
