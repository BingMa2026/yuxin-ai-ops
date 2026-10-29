from fastapi import APIRouter

from app.api.v1.module_billing.controller import CatalogAdminRouter, ClientBillingRouter, PricingRouter, SubscriptionAdminRouter

billing_operations_router = APIRouter(prefix="/operations/billing")
billing_client_router = APIRouter(prefix="/client/billing")
billing_operations_router.include_router(PricingRouter)
billing_operations_router.include_router(CatalogAdminRouter)
billing_operations_router.include_router(SubscriptionAdminRouter)
billing_client_router.include_router(ClientBillingRouter)
