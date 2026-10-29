from fastapi import APIRouter

from .controller import ClientUserOperationsRouter, UserOperationsAdminRouter

user_operations_admin_router = APIRouter(prefix="/operations/user-operations")
user_operations_client_router = APIRouter(prefix="/client/user-operations")
user_operations_admin_router.include_router(UserOperationsAdminRouter)
user_operations_client_router.include_router(ClientUserOperationsRouter)
