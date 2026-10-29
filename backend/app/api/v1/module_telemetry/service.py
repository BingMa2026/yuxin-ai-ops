from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException

from .model import TelemetryEventModel
from .schema import (
    TelemetryBatchIn,
    TelemetryBatchOut,
    TelemetryDiagnosticsOut,
    TelemetryEventDiagnosticOut,
    TelemetryTypeCount,
)


class TelemetryService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def ingest(self, data: TelemetryBatchIn) -> TelemetryBatchOut:
        if not self.auth.app_id or not self.auth.user.id:
            raise CustomException(msg="客户端认证上下文无效", status_code=401)

        accepted = 0
        duplicated = 0
        for event in data.events:
            row = TelemetryEventModel(
                app_id=self.auth.app_id,
                user_id=self.auth.user.id,
                event_id=event.event_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                source=event.source,
                client_version=event.client_version,
                session_ref=event.session_ref,
                project_ref=event.project_ref,
                task_ref=event.task_ref,
                critical=event.critical,
                event_metadata=event.metadata,
            )
            try:
                async with self.db.begin_nested():
                    self.db.add(row)
                    await self.db.flush()
            except IntegrityError:
                duplicated += 1
            else:
                accepted += 1
        return TelemetryBatchOut(accepted=accepted, duplicated=duplicated)

    async def diagnostics(self) -> TelemetryDiagnosticsOut:
        if not self.auth.app_id:
            raise CustomException(msg="请先选择客户端", status_code=409)
        total, latest_event, latest_received = (
            await self.db.execute(
                select(
                    func.count(TelemetryEventModel.id),
                    func.max(TelemetryEventModel.occurred_at),
                    func.max(TelemetryEventModel.created_time),
                ).where(
                    TelemetryEventModel.app_id == self.auth.app_id,
                    TelemetryEventModel.is_deleted.is_(False),
                )
            )
        ).one()
        latest = await self.db.scalar(
            select(TelemetryEventModel)
            .where(
                TelemetryEventModel.app_id == self.auth.app_id,
                TelemetryEventModel.is_deleted.is_(False),
            )
            .order_by(TelemetryEventModel.occurred_at.desc())
        )
        rows = (
            await self.db.execute(
                select(TelemetryEventModel.event_type, func.count(TelemetryEventModel.id))
                .where(
                    TelemetryEventModel.app_id == self.auth.app_id,
                    TelemetryEventModel.is_deleted.is_(False),
                )
                .group_by(TelemetryEventModel.event_type)
                .order_by(func.count(TelemetryEventModel.id).desc())
                .limit(30)
            )
        ).all()
        delay = None
        if latest and latest.created_time and latest.occurred_at:
            delay = max(0, int((latest.created_time - latest.occurred_at).total_seconds()))
        return TelemetryDiagnosticsOut(
            app_id=self.auth.app_id,
            total_events=int(total or 0),
            latest_event_at=latest_event,
            latest_received_at=latest_received,
            latest_client_version=latest.client_version if latest else None,
            delivery_delay_seconds=delay,
            event_types=[TelemetryTypeCount(event_type=event_type, count=int(count or 0)) for event_type, count in rows],
        )

    async def event_diagnostic(self, event_id: str) -> TelemetryEventDiagnosticOut:
        if not self.auth.app_id:
            raise CustomException(msg="请先选择客户端", status_code=409)
        event = await self.db.scalar(
            select(TelemetryEventModel).where(
                TelemetryEventModel.app_id == self.auth.app_id,
                TelemetryEventModel.event_id == event_id,
                TelemetryEventModel.is_deleted.is_(False),
            )
        )
        if not event:
            raise CustomException(msg="遥测事件不存在", status_code=404)
        return TelemetryEventDiagnosticOut(
            event_id=event.event_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            received_at=event.created_time,
            user_id=event.user_id,
            client_version=event.client_version,
            source=event.source,
            critical=event.critical,
        )
