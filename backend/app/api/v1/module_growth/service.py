from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_billing.model import AppPricingStrategyModel
from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.model import ClientUserModel, ClientUserSegmentModel
from app.core.exceptions import CustomException

from .defaults import default_drafts
from .engine import utc
from .model import GrowthPolicyModel
from .schema import IncentivePolicy, RuleDraftIn


async def lock_app(db: AsyncSession, app_id: int) -> ClientAppModel:
    if not app_id:
        raise CustomException(msg="请先选择客户端", status_code=409)
    app = await db.scalar(select(ClientAppModel).where(ClientAppModel.id == app_id, ClientAppModel.is_deleted == False).with_for_update())
    if not app:
        raise CustomException(msg="客户端不存在", status_code=404)
    return app


async def client_user(db: AsyncSession, app_id: int, user_id: int, *, lock: bool = False) -> ClientUserModel:
    stmt = select(ClientUserModel).where(ClientUserModel.app_id == app_id, ClientUserModel.id == user_id, ClientUserModel.is_deleted == False)
    user = await db.scalar(stmt.with_for_update() if lock else stmt)
    if not user:
        raise CustomException(msg="用户不存在", status_code=404)
    return user


def public_row(row: Any, fields: tuple[str, ...]) -> dict:
    return {key: utc(value) if isinstance(value := getattr(row, key), datetime) else value for key in fields}


RULE_FIELDS = ("id", "key", "kind", "name", "version", "status", "config", "effective_at", "created_time", "used_credits", "used_cash_fen")


class PolicyService:
    def __init__(self, db: AsyncSession, app_id: int, operator_id: int | None = None):
        self.db, self.app_id, self.operator_id = db, app_id, operator_id

    async def list(self, kind: str | None = None) -> list[dict]:
        stmt = select(GrowthPolicyModel).where(GrowthPolicyModel.app_id == self.app_id, GrowthPolicyModel.is_deleted == False)
        if kind:
            stmt = stmt.where(GrowthPolicyModel.kind == kind)
        return [public_row(r, RULE_FIELDS) for r in (await self.db.scalars(stmt.order_by(GrowthPolicyModel.id.desc()))).all()]

    async def seed(self) -> list[dict]:
        await lock_app(self.db, self.app_id)
        existing = set((await self.db.scalars(select(GrowthPolicyModel.key).where(GrowthPolicyModel.app_id == self.app_id))).all())
        for draft in default_drafts():
            if draft.key not in existing:
                await self.save(draft)
        return await self.list()

    async def save(self, data: RuleDraftIn) -> dict:
        await lock_app(self.db, self.app_id)
        version = int(await self.db.scalar(select(func.max(GrowthPolicyModel.version)).where(GrowthPolicyModel.app_id == self.app_id, GrowthPolicyModel.key == data.key)) or 0) + 1
        previous = await self.db.scalar(select(GrowthPolicyModel).where(GrowthPolicyModel.app_id == self.app_id, GrowthPolicyModel.key == data.key).order_by(GrowthPolicyModel.version.desc()).limit(1))
        if previous and previous.kind != data.kind:
            raise CustomException(msg="规则编号不能改变类别", status_code=409)
        row = GrowthPolicyModel(
            app_id=self.app_id, key=data.key, kind=data.kind, name=data.name, version=version, status="draft", config=data.config.model_dump(mode="json"), operator_id=self.operator_id
        )
        self.db.add(row)
        await self.db.flush()
        return public_row(row, RULE_FIELDS)

    async def save_and_publish(self, data: RuleDraftIn) -> dict:
        # A failed publish must never leave a new draft or replace the active version.
        async with self.db.begin_nested():
            row = await self.save(data)
            return await self.publish(row["id"], datetime.now(UTC))

    async def get(self, rule_id: int) -> GrowthPolicyModel:
        row = await self.db.scalar(select(GrowthPolicyModel).where(GrowthPolicyModel.id == rule_id, GrowthPolicyModel.app_id == self.app_id, GrowthPolicyModel.is_deleted == False))
        if not row:
            raise CustomException(msg="规则不存在", status_code=404)
        return row

    async def active(self, kind: str, *, at: datetime | None = None) -> list[GrowthPolicyModel]:
        at = utc(at or datetime.now(UTC))
        # A stopped latest version suppresses its predecessor; old versions remain
        # available for historical events, rather than being rewritten in-place.
        rows = (
            await self.db.scalars(
                select(GrowthPolicyModel)
                .where(
                    GrowthPolicyModel.app_id == self.app_id,
                    GrowthPolicyModel.kind == kind,
                    GrowthPolicyModel.status.in_(["published", "stopped"]),
                    GrowthPolicyModel.effective_at <= at,
                    GrowthPolicyModel.is_deleted == False,
                )
                .order_by(GrowthPolicyModel.effective_at.desc(), GrowthPolicyModel.id.desc())
            )
        ).all()
        latest = {}
        for row in rows:
            latest.setdefault(row.key, row)
        return [r for r in latest.values() if r.status == "published"]

    async def legacy_references(self) -> list[dict]:
        result = []
        strategies = (
            await self.db.scalars(
                select(AppPricingStrategyModel).where(AppPricingStrategyModel.app_id == self.app_id, AppPricingStrategyModel.is_deleted == False, AppPricingStrategyModel.status == "active")
            )
        ).all()
        for row in strategies:
            if row.scope_type == "level" and any(str(c).startswith("LV") for c in (row.scope_value or {}).get("level_codes", [])):
                result.append({"type": "pricing", "id": row.id, "name": row.name})
        segments = (
            await self.db.scalars(
                select(ClientUserSegmentModel).where(ClientUserSegmentModel.app_id == self.app_id, ClientUserSegmentModel.is_deleted == False, ClientUserSegmentModel.status == "active")
            )
        ).all()
        for row in segments:
            if (row.filters or {}).get("level_code"):
                result.append({"type": "segment", "id": row.id, "name": row.name})
        return result

    async def publish(self, rule_id: int, effective_at: datetime) -> dict:
        await lock_app(self.db, self.app_id)
        row = await self.get(rule_id)
        if row.status != "draft":
            raise CustomException(msg="只能发布草稿，新调整请保存为新版本", status_code=409)
        if effective_at.tzinfo is None:
            raise CustomException(msg="生效时间必须包含时区", status_code=422)
        if row.kind == "usage" and await self.legacy_references():
            raise CustomException(msg="仍有旧LV等级定价或分群引用，请迁移后发布", status_code=409)
        if row.kind == "incentive":
            policy = IncentivePolicy.model_validate(row.config)
            if any(a.asset == "credits" for a in policy.actions):
                from app.api.v1.module_client.app.model_policy import require_platform_model

                await require_platform_model(self.db, self.app_id)
            if policy.mode != "simulation" and any(a.asset == "credits" for a in policy.actions) and policy.budget_credits <= 0:
                raise CustomException(msg="请设置大于0的算力积分预算", status_code=422)
            if policy.mode != "simulation" and any(a.asset == "cash" for a in policy.actions) and policy.budget_cash_fen <= 0:
                raise CustomException(msg="请设置大于0的现金预算", status_code=422)
            if not await self.active("rights", at=effective_at):
                raise CustomException(msg="请先发布在该时间生效的权益政策", status_code=409)
        row.status, row.effective_at = "published", max(utc(effective_at), datetime.now(UTC))
        await self.db.flush()
        return public_row(row, RULE_FIELDS)

    async def stop(self, rule_id: int) -> dict:
        await lock_app(self.db, self.app_id)
        row = await self.get(rule_id)
        if row.status != "published":
            raise CustomException(msg="只能停用已发布规则", status_code=409)
        latest = await self.db.scalar(
            select(GrowthPolicyModel)
            .where(GrowthPolicyModel.app_id == self.app_id, GrowthPolicyModel.key == row.key, GrowthPolicyModel.status.in_(["published", "stopped"]))
            .order_by(GrowthPolicyModel.effective_at.desc(), GrowthPolicyModel.id.desc())
            .limit(1)
        )
        if latest.id != row.id:
            raise CustomException(msg="该版本已被新版本替代，请操作最新发布版本", status_code=409)
        # New tombstone version preserves the rule used by events before stop.
        version = int(await self.db.scalar(select(func.max(GrowthPolicyModel.version)).where(GrowthPolicyModel.app_id == self.app_id, GrowthPolicyModel.key == row.key)) or 0) + 1
        stopped = GrowthPolicyModel(
            app_id=self.app_id,
            key=row.key,
            kind=row.kind,
            name=row.name,
            version=version,
            config=row.config,
            status="stopped",
            effective_at=max(datetime.now(UTC), utc(row.effective_at)),
            operator_id=self.operator_id,
        )
        self.db.add(stopped)
        await self.db.flush()
        return public_row(stopped, RULE_FIELDS)
