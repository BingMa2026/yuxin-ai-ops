from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CustomException

from .model import GrowthTaskModel
from .referral_service import ReferralService
from .reward_service import RewardService
from .schema import TaskClaimIn, TaskCompleteIn
from .service import lock_app


class TaskService:
    def __init__(self, db: AsyncSession, app_id: int):
        self.db, self.app_id = db, app_id

    async def get(self, task_id: int, user_id: int | None = None) -> GrowthTaskModel:
        query = select(GrowthTaskModel).where(GrowthTaskModel.app_id == self.app_id, GrowthTaskModel.id == task_id)
        if user_id is not None:
            query = query.where(GrowthTaskModel.user_id == user_id)
        task = await self.db.scalar(query)
        if not task:
            raise CustomException(msg="任务不存在", status_code=404)
        return task

    async def claim(self, user_id: int, data: TaskClaimIn) -> GrowthTaskModel:
        await lock_app(self.db, self.app_id)
        task = await self.db.scalar(select(GrowthTaskModel).where(GrowthTaskModel.app_id == self.app_id, GrowthTaskModel.user_id == user_id, GrowthTaskModel.local_task_id == data.local_task_id))
        if task:
            if task.project_ref != data.project_ref or task.kind != data.kind:
                raise CustomException(msg="同一任务标识不能用于不同项目或任务类型", status_code=409)
            if task.status in {"failed", "cancelled"}:
                task.status = "started"
                await self.db.flush()
            return task
        task = GrowthTaskModel(app_id=self.app_id, user_id=user_id, **data.model_dump())
        self.db.add(task)
        await self.db.flush()
        return task

    async def complete(self, task_id: int, user_id: int, data: TaskCompleteIn) -> GrowthTaskModel:
        await lock_app(self.db, self.app_id)
        task = await self.get(task_id, user_id)
        if task.status != "started":
            return task
        if data.result == "completed" and not data.artifact_ref:
            raise CustomException(msg="完成任务需提供成果标识", status_code=422)
        task.completed_at = datetime.now(UTC)
        task.artifact_ref = data.artifact_ref
        task.status = "review" if data.result == "completed" else data.result
        await self.db.flush()
        return task

    async def review(self, task_id: int, approved: bool, reason: str) -> GrowthTaskModel:
        await lock_app(self.db, self.app_id)
        task = await self.get(task_id)
        if task.status != "review":
            raise CustomException(msg="仅待核验任务可审核", status_code=409)
        task.status = "verified" if approved else "rejected"
        task.review_reason = reason
        if approved:
            task.verified_at = datetime.now(UTC)
            duplicate = await self.db.scalar(
                select(GrowthTaskModel.id)
                .where(
                    GrowthTaskModel.app_id == self.app_id,
                    GrowthTaskModel.user_id == task.user_id,
                    GrowthTaskModel.project_ref == task.project_ref,
                    GrowthTaskModel.artifact_ref == task.artifact_ref,
                    GrowthTaskModel.status == "verified",
                    GrowthTaskModel.id != task.id,
                )
                .limit(1)
            )
            if duplicate:
                task.status, task.review_reason = "rejected", "重复成果，不重复计入有效任务或奖励"
                await self.db.flush()
                return task
            profile = await ReferralService(self.db, self.app_id).profile(task.user_id)
            first = profile.first_task_at is None and task.kind in {"tender_analysis", "full_review"}
            if first:
                profile.first_task_at = task.verified_at
            rewards = RewardService(self.db, self.app_id)
            facts = {"task_id": task.id, "project_ref": task.project_ref, "artifact_ref": task.artifact_ref}
            # One business fact, one base reward. Retried local task IDs cannot mint another artifact.
            if first:
                await rewards.emit(task.user_id, "first_task", f"first_task:{task.user_id}", facts)
            elif task.kind == "cocreate":
                await rewards.emit(task.user_id, "cocreate", f"cocreate:{task.user_id}:{task.project_ref}", facts)
            else:
                import hashlib

                digest = hashlib.sha256(f"{task.user_id}:{task.project_ref}:{task.artifact_ref}".encode()).hexdigest()
                await rewards.emit(task.user_id, "artifact", f"artifact:{digest}", facts)
        await self.db.flush()
        return task
