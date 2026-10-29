from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_client.user.model import ClientUserModel, ClientUserSegmentModel
from app.core.base_schema import AuthSchema, PageResultSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException

from .model import (
    ClientMessageCampaignModel,
    ClientMessageDeliveryModel,
    ClientMessageTemplateModel,
    ClientSupportMessageModel,
    ClientSupportTicketModel,
)
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

SLA_HOURS = {"urgent": 4, "high": 24, "normal": 48, "low": 72}


def _app_id(auth: AuthSchema) -> int:
    if not auth.app_id:
        raise CustomException(msg="请先选择客户端", status_code=409)
    return auth.app_id


def _page(page_no: int, page_size: int, total: int, items: list):
    return PageResultSchema(page_no=page_no, page_size=page_size, total=total, has_next=page_no * page_size < total, items=items)


class SupportService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db
        self.app_id = _app_id(auth)

    async def _ticket(self, ticket_id: int, *, client_only: bool = False) -> ClientSupportTicketModel:
        stmt = select(ClientSupportTicketModel).where(
            ClientSupportTicketModel.id == ticket_id,
            ClientSupportTicketModel.app_id == self.app_id,
            ClientSupportTicketModel.is_deleted == False,
        )
        if client_only:
            stmt = stmt.where(ClientSupportTicketModel.user_id == self.auth.user.id)
        ticket = await self.db.scalar(stmt)
        if not ticket:
            raise CustomException(msg="工单不存在", status_code=404)
        return ticket

    async def _out(self, ticket: ClientSupportTicketModel, *, include_internal: bool) -> TicketOutSchema:
        user = await self.db.scalar(select(ClientUserModel).where(ClientUserModel.id == ticket.user_id))
        message_stmt = select(ClientSupportMessageModel).where(
            ClientSupportMessageModel.ticket_id == ticket.id,
            ClientSupportMessageModel.app_id == self.app_id,
            ClientSupportMessageModel.is_deleted == False,
        )
        if not include_internal:
            message_stmt = message_stmt.where(ClientSupportMessageModel.internal == False)
        messages = list((await self.db.scalars(message_stmt.order_by(ClientSupportMessageModel.id.asc()))).all())
        result = TicketOutSchema.model_validate(ticket)
        result.username = user.username if user else None
        result.display_name = user.display_name if user else None
        result.messages = [TicketMessageOutSchema.model_validate(item) for item in messages]
        return result

    async def create(self, data: TicketCreateSchema) -> TicketOutSchema:
        now = datetime.now(UTC)
        ticket = ClientSupportTicketModel(
            app_id=self.app_id,
            user_id=self.auth.user.id,
            ticket_no=f"TK{now.strftime('%Y%m%d')}{uuid4().hex[:10].upper()}",
            **data.model_dump(),
            sla_due_at=now + timedelta(hours=SLA_HOURS[data.priority]),
            created_id=None,
            updated_id=None,
        )
        self.db.add(ticket)
        await self.db.flush()
        return await self._out(ticket, include_internal=False)

    async def list(
        self, page_no: int, page_size: int, *, client_only: bool, keyword: str | None, kind: str | None, category: str | None, status: str | None, priority: str | None
    ) -> PageResultSchema[TicketOutSchema]:
        conditions = [ClientSupportTicketModel.app_id == self.app_id, ClientSupportTicketModel.is_deleted == False]
        if client_only:
            conditions.append(ClientSupportTicketModel.user_id == self.auth.user.id)
        if keyword:
            conditions.append(or_(ClientSupportTicketModel.ticket_no.ilike(f"%{keyword}%"), ClientSupportTicketModel.subject.ilike(f"%{keyword}%")))
        if kind:
            conditions.append(ClientSupportTicketModel.kind == kind)
        if category:
            conditions.append(ClientSupportTicketModel.category == category)
        if status:
            conditions.append(ClientSupportTicketModel.status == status)
        if priority:
            conditions.append(ClientSupportTicketModel.priority == priority)
        total = int(await self.db.scalar(select(func.count()).select_from(ClientSupportTicketModel).where(*conditions)) or 0)
        rows = list((await self.db.scalars(select(ClientSupportTicketModel).where(*conditions).order_by(ClientSupportTicketModel.id.desc()).offset((page_no - 1) * page_size).limit(page_size))).all())
        return _page(page_no, page_size, total, [await self._out(row, include_internal=not client_only) for row in rows])

    async def detail(self, ticket_id: int, *, client_only: bool) -> TicketOutSchema:
        return await self._out(await self._ticket(ticket_id, client_only=client_only), include_internal=not client_only)

    async def update(self, ticket_id: int, data: TicketUpdateSchema) -> TicketOutSchema:
        from app.api.v1.module_growth.reward_service import RewardService
        from app.api.v1.module_growth.service import lock_app

        await lock_app(self.db, self.app_id)
        ticket = await self._ticket(ticket_id)
        was_adopted = ticket.adopted
        values = data.model_dump(exclude_unset=True)
        if was_adopted and ticket.kind == "feedback":
            if values.get("adopted") is False or ("value_grade" in values and values["value_grade"] != ticket.value_grade):
                raise CustomException(msg="已采纳反馈的采纳状态和价值等级已进入奖励记录，不能直接修改", status_code=409)
        for key, value in values.items():
            setattr(ticket, key, value)
        if data.priority:
            ticket.sla_due_at = ticket.created_time + timedelta(hours=SLA_HOURS[data.priority])
        if data.status in {"resolved", "closed"}:
            ticket.resolved_at = datetime.now(UTC)
        ticket.updated_id = self.auth.user.id
        await self.db.flush()
        if ticket.kind == "feedback" and ticket.adopted and not was_adopted:
            ticket.value_grade = ticket.value_grade or "C"
            await RewardService(self.db, self.app_id).emit(ticket.user_id, "feedback", f"feedback:{ticket.id}", {"ticket_id": ticket.id, "feedback_grade": ticket.value_grade})
        return await self._out(ticket, include_internal=True)

    async def reply(self, ticket_id: int, data: TicketMessageCreateSchema, *, client_only: bool) -> TicketMessageOutSchema:
        ticket = await self._ticket(ticket_id, client_only=client_only)
        if ticket.status == "closed":
            raise CustomException(msg="已关闭工单不能继续回复")
        if client_only and data.internal:
            raise CustomException(msg="客户端不能发送内部备注", status_code=403)
        sender_type = "client" if client_only else "staff"
        message = ClientSupportMessageModel(
            app_id=self.app_id,
            ticket_id=ticket.id,
            sender_type=sender_type,
            sender_id=self.auth.user.id,
            **data.model_dump(),
        )
        self.db.add(message)
        ticket.last_replied_at = datetime.now(UTC)
        if client_only:
            ticket.status = "processing"
        elif not data.internal:
            ticket.status = "waiting_user"
            self.db.add(
                ClientMessageDeliveryModel(
                    app_id=self.app_id,
                    campaign_id=None,
                    user_id=ticket.user_id,
                    message_type="ticket_reply",
                    title=f"工单 {ticket.ticket_no} 有新回复",
                    content=data.content[:500],
                    content_type="plain_text",
                    deep_link=f"/settings/support?ticketId={ticket.id}",
                    resource_type="support_ticket",
                    resource_id=str(ticket.id),
                    delivered_at=datetime.now(UTC),
                    status="delivered",
                )
            )
        await self.db.flush()
        return TicketMessageOutSchema.model_validate(message)


class MessagingService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db
        self.app_id = _app_id(auth)

    async def templates(self) -> list[MessageTemplateOutSchema]:
        rows = list(
            (
                await self.db.scalars(
                    select(ClientMessageTemplateModel)
                    .where(ClientMessageTemplateModel.app_id == self.app_id, ClientMessageTemplateModel.is_deleted == False)
                    .order_by(ClientMessageTemplateModel.id.desc())
                )
            ).all()
        )
        return [MessageTemplateOutSchema.model_validate(item) for item in rows]

    async def create_template(self, data: MessageTemplateCreateSchema) -> MessageTemplateOutSchema:
        duplicate = await self.db.scalar(
            select(ClientMessageTemplateModel.id).where(ClientMessageTemplateModel.app_id == self.app_id, ClientMessageTemplateModel.name == data.name, ClientMessageTemplateModel.is_deleted == False)
        )
        if duplicate:
            raise CustomException(msg="模板名称已存在")
        row = ClientMessageTemplateModel(app_id=self.app_id, **data.model_dump(), created_id=self.auth.user.id, updated_id=self.auth.user.id)
        self.db.add(row)
        await self.db.flush()
        return MessageTemplateOutSchema.model_validate(row)

    async def update_template(self, template_id: int, data: MessageTemplateUpdateSchema) -> MessageTemplateOutSchema:
        row = await self.db.scalar(
            select(ClientMessageTemplateModel).where(ClientMessageTemplateModel.id == template_id, ClientMessageTemplateModel.app_id == self.app_id, ClientMessageTemplateModel.is_deleted == False)
        )
        if not row:
            raise CustomException(msg="消息模板不存在", status_code=404)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        row.updated_id = self.auth.user.id
        await self.db.flush()
        return MessageTemplateOutSchema.model_validate(row)

    async def campaigns(self) -> list[CampaignOutSchema]:
        rows = list(
            (
                await self.db.scalars(
                    select(ClientMessageCampaignModel)
                    .where(ClientMessageCampaignModel.app_id == self.app_id, ClientMessageCampaignModel.is_deleted == False)
                    .order_by(ClientMessageCampaignModel.id.desc())
                )
            ).all()
        )
        return [CampaignOutSchema.model_validate(item) for item in rows]

    async def create_campaign(self, data: CampaignCreateSchema) -> CampaignOutSchema:
        status = "draft"
        if data.send_now:
            status = "sending"
        elif data.scheduled_at:
            status = "scheduled"
        row = ClientMessageCampaignModel(
            app_id=self.app_id,
            **data.model_dump(exclude={"send_now"}),
            status=status,
            created_id=self.auth.user.id,
            updated_id=self.auth.user.id,
        )
        self.db.add(row)
        await self.db.flush()
        if data.send_now:
            await self.send(row)
        return CampaignOutSchema.model_validate(row)

    async def update_campaign(self, campaign_id: int, data: CampaignUpdateSchema) -> CampaignOutSchema:
        row = await self.db.scalar(
            select(ClientMessageCampaignModel).where(ClientMessageCampaignModel.id == campaign_id, ClientMessageCampaignModel.app_id == self.app_id, ClientMessageCampaignModel.is_deleted == False)
        )
        if not row:
            raise CustomException(msg="触达任务不存在", status_code=404)
        if row.status not in {"draft", "scheduled"}:
            raise CustomException(msg="已发送任务不能修改")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        row.status = "scheduled" if row.scheduled_at else "draft"
        row.updated_id = self.auth.user.id
        await self.db.flush()
        return CampaignOutSchema.model_validate(row)

    async def _audience(self, campaign: ClientMessageCampaignModel) -> list[int]:
        stmt = select(ClientUserModel.id).where(ClientUserModel.app_id == self.app_id, ClientUserModel.status == "active", ClientUserModel.is_deleted == False)
        value = campaign.audience_value or {}
        if campaign.audience_type == "new":
            stmt = stmt.where(ClientUserModel.registered_at >= datetime.now(UTC) - timedelta(days=30))
        elif campaign.audience_type == "level":
            from app.api.v1.module_growth.filters import grade_codes

            stmt = stmt.where(grade_codes(self.app_id, value.get("level_codes") or []))
        elif campaign.audience_type == "users":
            stmt = stmt.where(ClientUserModel.id.in_(value.get("user_ids") or []))
        elif campaign.audience_type == "segment":
            segment = await self.db.scalar(
                select(ClientUserSegmentModel).where(ClientUserSegmentModel.id == value.get("segment_id"), ClientUserSegmentModel.app_id == self.app_id, ClientUserSegmentModel.is_deleted == False)
            )
            if not segment:
                raise CustomException(msg="用户分群不存在")
            filters = segment.filters or {}
            from app.api.v1.module_growth.filters import segment_conditions

            stmt = stmt.where(*segment_conditions(self.app_id, filters))
            if filters.get("registered_days"):
                stmt = stmt.where(ClientUserModel.registered_at >= datetime.now(UTC) - timedelta(days=int(filters["registered_days"])))
        return list((await self.db.scalars(stmt)).all())

    async def preview_audience(self, data: CampaignAudiencePreviewSchema) -> CampaignAudiencePreviewOutSchema:
        class Audience:
            audience_type = data.audience_type
            audience_value = data.audience_value

        user_ids = await self._audience(Audience())  # type: ignore[arg-type]
        if not user_ids:
            return CampaignAudiencePreviewOutSchema(target_count=0)
        rows = list(
            (
                await self.db.scalars(
                    select(ClientUserModel)
                    .where(
                        ClientUserModel.app_id == self.app_id,
                        ClientUserModel.id.in_(user_ids[:5]),
                        ClientUserModel.is_deleted == False,
                    )
                    .order_by(ClientUserModel.id.desc())
                )
            ).all()
        )
        return CampaignAudiencePreviewOutSchema(
            target_count=len(user_ids),
            sample_users=[{"id": row.id, "name": row.display_name or row.username, "level_code": row.level_code} for row in rows],
        )

    async def send(self, campaign: ClientMessageCampaignModel) -> None:
        user_ids = await self._audience(campaign)
        now = datetime.now(UTC)
        for user_id in user_ids:
            self.db.add(
                ClientMessageDeliveryModel(
                    app_id=self.app_id,
                    campaign_id=campaign.id,
                    user_id=user_id,
                    message_type="campaign",
                    title=campaign.title,
                    content=campaign.content,
                    content_type=campaign.content_type,
                    delivered_at=now,
                    status="delivered",
                )
            )
        campaign.status = "sent"
        campaign.sent_at = now
        campaign.target_count = len(user_ids)
        campaign.delivered_count = len(user_ids)
        await self.db.flush()

    async def cancel(self, campaign_id: int) -> CampaignOutSchema:
        row = await self.db.scalar(
            select(ClientMessageCampaignModel).where(ClientMessageCampaignModel.id == campaign_id, ClientMessageCampaignModel.app_id == self.app_id, ClientMessageCampaignModel.is_deleted == False)
        )
        if not row:
            raise CustomException(msg="触达任务不存在", status_code=404)
        if row.status not in {"draft", "scheduled"}:
            raise CustomException(msg="只有草稿或定时任务可以取消")
        row.status = "cancelled"
        row.cancelled_at = datetime.now(UTC)
        await self.db.flush()
        return CampaignOutSchema.model_validate(row)

    async def deliveries(
        self, page_no: int, page_size: int, *, keyword: str | None = None, message_type: str | None = None, read_status: str | None = None
    ) -> PageResultSchema[MessageDeliveryOutSchema]:
        stmt = (
            select(ClientMessageDeliveryModel, ClientUserModel)
            .join(ClientUserModel, (ClientUserModel.id == ClientMessageDeliveryModel.user_id) & (ClientUserModel.app_id == ClientMessageDeliveryModel.app_id))
            .where(ClientMessageDeliveryModel.app_id == self.app_id, ClientMessageDeliveryModel.is_deleted == False)
        )
        if keyword:
            value = f"%{keyword}%"
            stmt = stmt.where(or_(ClientMessageDeliveryModel.title.ilike(value), ClientUserModel.username.ilike(value), ClientUserModel.display_name.ilike(value)))
        if message_type:
            stmt = stmt.where(ClientMessageDeliveryModel.message_type == message_type)
        if read_status == "read":
            stmt = stmt.where(ClientMessageDeliveryModel.read_at.is_not(None))
        elif read_status == "unread":
            stmt = stmt.where(ClientMessageDeliveryModel.read_at.is_(None))
        total = int(await self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = (await self.db.execute(stmt.order_by(ClientMessageDeliveryModel.id.desc()).offset((page_no - 1) * page_size).limit(page_size))).all()
        items = [
            MessageDeliveryOutSchema(
                **ClientInboxMessageOutSchema.model_validate(row).model_dump(), user_id=row.user_id, username=user.username, display_name=user.display_name, campaign_id=row.campaign_id
            )
            for row, user in rows
        ]
        return _page(page_no, page_size, total, items)

    async def inbox(self) -> list[ClientInboxMessageOutSchema]:
        rows = list(
            (
                await self.db.scalars(
                    select(ClientMessageDeliveryModel)
                    .where(ClientMessageDeliveryModel.app_id == self.app_id, ClientMessageDeliveryModel.user_id == self.auth.user.id, ClientMessageDeliveryModel.is_deleted == False)
                    .order_by(ClientMessageDeliveryModel.id.desc())
                    .limit(100)
                )
            ).all()
        )
        return [ClientInboxMessageOutSchema.model_validate(item) for item in rows]

    async def read(self, delivery_id: int) -> ClientInboxMessageOutSchema:
        row = await self.db.scalar(
            select(ClientMessageDeliveryModel).where(
                ClientMessageDeliveryModel.id == delivery_id,
                ClientMessageDeliveryModel.app_id == self.app_id,
                ClientMessageDeliveryModel.user_id == self.auth.user.id,
                ClientMessageDeliveryModel.is_deleted == False,
            )
        )
        if not row:
            raise CustomException(msg="消息不存在", status_code=404)
        if not row.read_at:
            row.read_at = datetime.now(UTC)
            row.status = "read"
            if row.campaign_id:
                campaign = await self.db.scalar(select(ClientMessageCampaignModel).where(ClientMessageCampaignModel.id == row.campaign_id))
                if campaign:
                    campaign.read_count += 1
        await self.db.flush()
        return ClientInboxMessageOutSchema.model_validate(row)

    async def read_all(self) -> int:
        rows = list(
            (
                await self.db.scalars(
                    select(ClientMessageDeliveryModel).where(
                        ClientMessageDeliveryModel.app_id == self.app_id,
                        ClientMessageDeliveryModel.user_id == self.auth.user.id,
                        ClientMessageDeliveryModel.read_at.is_(None),
                        ClientMessageDeliveryModel.is_deleted == False,
                    )
                )
            ).all()
        )
        for row in rows:
            await self.read(row.id)
        return len(rows)


async def run_scheduled_campaigns() -> None:
    async with async_db_session() as db, db.begin():
        now = datetime.now(UTC)
        rows = list(
            (
                await db.scalars(
                    select(ClientMessageCampaignModel)
                    .where(ClientMessageCampaignModel.status == "scheduled", ClientMessageCampaignModel.scheduled_at <= now, ClientMessageCampaignModel.is_deleted == False)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for campaign in rows:
            auth = AuthSchema(app_id=campaign.app_id)
            await MessagingService(auth, db).send(campaign)
