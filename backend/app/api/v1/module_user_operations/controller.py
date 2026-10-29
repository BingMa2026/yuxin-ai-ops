from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Path, Query, Request, Security, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_common.file.service import FileService
from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PageResultSchema, PaginationQueryParam, UploadResponseSchema
from app.core.client_dependencies import get_current_client_user
from app.core.dependencies import AuthPermission, db_getter
from app.core.exceptions import CustomException
from app.core.router_class import OperationLogRoute

from .schema import (
    CampaignAudiencePreviewOutSchema,
    CampaignAudiencePreviewSchema,
    CampaignCreateSchema,
    CampaignOutSchema,
    CampaignUpdateSchema,
    ClientInboxMessageOutSchema,
    MessageDeliveryOutSchema,
    MessageTemplateCreateSchema,
    MessageTemplateOutSchema,
    MessageTemplateUpdateSchema,
    TicketCreateSchema,
    TicketMessageCreateSchema,
    TicketMessageOutSchema,
    TicketOutSchema,
    TicketUpdateSchema,
)
from .service import MessagingService, SupportService

UserOperationsAdminRouter = APIRouter(route_class=OperationLogRoute, tags=["用户运营"])
ClientUserOperationsRouter = APIRouter(tags=["客户端工单与消息"])


@UserOperationsAdminRouter.get("/tickets", response_model=ResponseSchema[PageResultSchema[TicketOutSchema]])
async def admin_tickets(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:support:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    keyword: Annotated[str | None, Query()] = None,
    kind: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    ticket_status: Annotated[str | None, Query(alias="status")] = None,
    priority: Annotated[str | None, Query()] = None,
) -> JSONResponse:
    return SuccessResponse(
        data=await SupportService(auth, db).list(page.page_no, page.page_size, client_only=False, keyword=keyword, kind=kind, category=category, status=ticket_status, priority=priority)
    )


@UserOperationsAdminRouter.get("/tickets/{ticket_id}", response_model=ResponseSchema[TicketOutSchema])
async def admin_ticket(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:support:list"]))], db: Annotated[AsyncSession, Depends(db_getter)], ticket_id: Annotated[int, Path(gt=0)]
) -> JSONResponse:
    return SuccessResponse(data=await SupportService(auth, db).detail(ticket_id, client_only=False))


@UserOperationsAdminRouter.patch("/tickets/{ticket_id}", response_model=ResponseSchema[TicketOutSchema])
async def update_ticket(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:support:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ticket_id: Annotated[int, Path(gt=0)],
    data: Annotated[TicketUpdateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await SupportService(auth, db).update(ticket_id, data), msg="工单已更新")


@UserOperationsAdminRouter.post("/tickets/{ticket_id}/messages", response_model=ResponseSchema[TicketMessageOutSchema])
async def admin_reply(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:support:reply"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ticket_id: Annotated[int, Path(gt=0)],
    data: Annotated[TicketMessageCreateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await SupportService(auth, db).reply(ticket_id, data, client_only=False), msg="回复已发送")


@UserOperationsAdminRouter.get("/message-templates", response_model=ResponseSchema[list[MessageTemplateOutSchema]])
async def templates(auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:message:list"]))], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await MessagingService(auth, db).templates())


@UserOperationsAdminRouter.post("/message-templates", response_model=ResponseSchema[MessageTemplateOutSchema], status_code=status.HTTP_201_CREATED)
async def create_template(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:message:create"]))], db: Annotated[AsyncSession, Depends(db_getter)], data: Annotated[MessageTemplateCreateSchema, Body()]
) -> JSONResponse:
    return SuccessResponse(data=await MessagingService(auth, db).create_template(data), msg="模板已创建", status_code=status.HTTP_201_CREATED)


@UserOperationsAdminRouter.patch("/message-templates/{template_id}", response_model=ResponseSchema[MessageTemplateOutSchema])
async def update_template(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:message:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    template_id: Annotated[int, Path(gt=0)],
    data: Annotated[MessageTemplateUpdateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await MessagingService(auth, db).update_template(template_id, data), msg="模板已更新")


@UserOperationsAdminRouter.get("/message-deliveries", response_model=ResponseSchema[PageResultSchema[MessageDeliveryOutSchema]])
async def message_deliveries(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:message:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    keyword: Annotated[str | None, Query(max_length=120)] = None,
    message_type: Annotated[str | None, Query(max_length=24)] = None,
    read_status: Annotated[str | None, Query(pattern="^(read|unread)$")] = None,
) -> JSONResponse:
    return SuccessResponse(data=await MessagingService(auth, db).deliveries(page.page_no, page.page_size, keyword=keyword, message_type=message_type, read_status=read_status))


@UserOperationsAdminRouter.get("/campaigns", response_model=ResponseSchema[list[CampaignOutSchema]])
async def campaigns(auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:message:list"]))], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await MessagingService(auth, db).campaigns())


@UserOperationsAdminRouter.post("/campaigns/audience-preview", response_model=ResponseSchema[CampaignAudiencePreviewOutSchema])
async def preview_campaign_audience(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:message:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[CampaignAudiencePreviewSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await MessagingService(auth, db).preview_audience(data))


@UserOperationsAdminRouter.post("/campaigns", response_model=ResponseSchema[CampaignOutSchema], status_code=status.HTTP_201_CREATED)
async def create_campaign(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:message:create"]))], db: Annotated[AsyncSession, Depends(db_getter)], data: Annotated[CampaignCreateSchema, Body()]
) -> JSONResponse:
    return SuccessResponse(data=await MessagingService(auth, db).create_campaign(data), msg="触达任务已创建", status_code=status.HTTP_201_CREATED)


@UserOperationsAdminRouter.patch("/campaigns/{campaign_id}", response_model=ResponseSchema[CampaignOutSchema])
async def update_campaign(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:message:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    campaign_id: Annotated[int, Path(gt=0)],
    data: Annotated[CampaignUpdateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await MessagingService(auth, db).update_campaign(campaign_id, data), msg="触达任务已更新")


@UserOperationsAdminRouter.post("/campaigns/{campaign_id}/cancel", response_model=ResponseSchema[CampaignOutSchema])
async def cancel_campaign(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:user:message:create"]))], db: Annotated[AsyncSession, Depends(db_getter)], campaign_id: Annotated[int, Path(gt=0)]
) -> JSONResponse:
    return SuccessResponse(data=await MessagingService(auth, db).cancel(campaign_id), msg="触达任务已取消")


@ClientUserOperationsRouter.post("/tickets", response_model=ResponseSchema[TicketOutSchema], status_code=status.HTTP_201_CREATED)
async def client_create_ticket(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)], db: Annotated[AsyncSession, Depends(db_getter)], data: Annotated[TicketCreateSchema, Body()]
) -> JSONResponse:
    return SuccessResponse(data=await SupportService(auth, db).create(data), msg="反馈已提交", status_code=status.HTTP_201_CREATED)


@ClientUserOperationsRouter.post("/attachments", response_model=ResponseSchema[UploadResponseSchema])
async def client_upload_attachment(
    request: Request,
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    file: Annotated[UploadFile, File(description="工单附件")],
) -> JSONResponse:
    allowed = {".jpg", ".jpeg", ".png", ".gif", ".pdf", ".txt", ".log"}
    filename = file.filename or ""
    extension = f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""
    if extension not in allowed:
        raise CustomException(msg="附件仅支持图片、PDF、日志或文本文件")
    result = await FileService.upload_service(
        base_url=str(request.base_url),
        file=file,
        upload_type="resource",
        target_path=f"feedback/{auth.app_id}/{auth.user.id}",
    )
    return SuccessResponse(data=result, msg="附件上传成功")


@ClientUserOperationsRouter.get("/tickets", response_model=ResponseSchema[PageResultSchema[TicketOutSchema]])
async def client_tickets(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)], db: Annotated[AsyncSession, Depends(db_getter)], page: Annotated[PaginationQueryParam, Depends()]
) -> JSONResponse:
    return SuccessResponse(data=await SupportService(auth, db).list(page.page_no, page.page_size, client_only=True, keyword=None, kind=None, category=None, status=None, priority=None))


@ClientUserOperationsRouter.get("/tickets/{ticket_id}", response_model=ResponseSchema[TicketOutSchema])
async def client_ticket(auth: Annotated[AuthSchema, Depends(get_current_client_user)], db: Annotated[AsyncSession, Depends(db_getter)], ticket_id: Annotated[int, Path(gt=0)]) -> JSONResponse:
    return SuccessResponse(data=await SupportService(auth, db).detail(ticket_id, client_only=True))


@ClientUserOperationsRouter.post("/tickets/{ticket_id}/messages", response_model=ResponseSchema[TicketMessageOutSchema])
async def client_reply(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ticket_id: Annotated[int, Path(gt=0)],
    data: Annotated[TicketMessageCreateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await SupportService(auth, db).reply(ticket_id, data, client_only=True), msg="补充内容已提交")


@ClientUserOperationsRouter.get("/messages", response_model=ResponseSchema[list[ClientInboxMessageOutSchema]])
async def inbox(auth: Annotated[AuthSchema, Depends(get_current_client_user)], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await MessagingService(auth, db).inbox())


@ClientUserOperationsRouter.patch("/messages/{delivery_id}/read", response_model=ResponseSchema[ClientInboxMessageOutSchema])
async def read_message(auth: Annotated[AuthSchema, Depends(get_current_client_user)], db: Annotated[AsyncSession, Depends(db_getter)], delivery_id: Annotated[int, Path(gt=0)]) -> JSONResponse:
    return SuccessResponse(data=await MessagingService(auth, db).read(delivery_id))


@ClientUserOperationsRouter.post("/messages/read-all", response_model=ResponseSchema[int])
async def read_all(auth: Annotated[AuthSchema, Depends(get_current_client_user)], db: Annotated[AsyncSession, Depends(db_getter)]) -> JSONResponse:
    return SuccessResponse(data=await MessagingService(auth, db).read_all(), msg="消息已全部标为已读")
