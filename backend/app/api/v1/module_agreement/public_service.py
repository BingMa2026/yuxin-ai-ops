from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_client.app.model import ClientAppModel
from app.core.exceptions import CustomException

from .crud import lock_app
from .model import AgreementAcceptanceModel, AgreementModel, AgreementSceneModel, AgreementVersionModel
from .schema import AcceptanceInput, PublicAgreement, PublicScene


class PublicAgreementService:
    def __init__(self, db: AsyncSession, app_id: int):
        self.db, self.app_id = db, app_id

    @classmethod
    async def for_code(cls, db: AsyncSession, app_code: str):
        app_id = await db.scalar(select(ClientAppModel.id).where(ClientAppModel.code == app_code, ClientAppModel.status == "active", ClientAppModel.is_deleted == False))
        if app_id is None:
            raise CustomException(msg="客户端不存在或已停用", status_code=404)
        return cls(db, app_id)

    async def agreement(self, code: str) -> PublicAgreement:
        result = (
            await self.db.execute(
                select(AgreementModel, AgreementVersionModel)
                .join(
                    AgreementVersionModel,
                    (AgreementVersionModel.agreement_id == AgreementModel.id)
                    & (AgreementVersionModel.app_id == AgreementModel.app_id)
                    & (AgreementVersionModel.version == AgreementModel.current_version),
                )
                .where(AgreementModel.app_id == self.app_id, AgreementModel.code == code, AgreementModel.status == "published", AgreementModel.is_deleted == False)
            )
        ).first()
        if not result:
            raise CustomException(msg="协议尚未发布或已归档", status_code=404)
        agreement, version = result
        return PublicAgreement(code=agreement.code, version_id=version.id, version=version.version, title=version.title, content=version.content, published_at=version.published_at)

    async def scene(self, code: str) -> PublicScene:
        scene = await self.db.scalar(select(AgreementSceneModel).where(AgreementSceneModel.app_id == self.app_id, AgreementSceneModel.code == code, AgreementSceneModel.is_deleted == False))
        if not scene:
            raise CustomException(msg="该场景尚未配置协议，请联系运营人员", status_code=404)
        agreements = []
        for row_id in scene.agreement_ids:
            agreement = await self.db.scalar(select(AgreementModel).where(AgreementModel.app_id == self.app_id, AgreementModel.id == row_id, AgreementModel.is_deleted == False))
            if not agreement:
                raise CustomException(msg="场景协议配置不完整", status_code=409)
            agreements.append(await self.agreement(agreement.code))
        return PublicScene(code=scene.code, name=scene.name, revision=scene.revision, require_acceptance=scene.require_acceptance, agreements=agreements)

    async def validate(self, code: str, acceptance: AcceptanceInput | None) -> PublicScene | None:
        await lock_app(self.db, self.app_id)
        configured = await self.db.scalar(select(AgreementSceneModel.id).where(AgreementSceneModel.app_id == self.app_id, AgreementSceneModel.code == code))
        # Existing integrations remain compatible until an operator explicitly
        # configures this scene. Once configured, deletion never bypasses validation.
        if not configured and acceptance is None:
            return None
        scene = await self.scene(code)
        if scene.require_acceptance:
            if acceptance is None:
                raise CustomException(msg="请阅读并同意当前场景的协议", status_code=409)
            expected = {item.version_id for item in scene.agreements}
            if acceptance.scene_revision != scene.revision or set(acceptance.version_ids) != expected or len(acceptance.version_ids) != len(expected):
                raise CustomException(msg="协议已更新，请重新阅读并确认", status_code=409)
        return scene

    async def record(self, scene: PublicScene | None, user_id: int, business_ref: str, acceptance: AcceptanceInput | None):
        if scene is None or acceptance is None:
            return
        # Optional reading scenes do not produce implied acceptance records.
        expected = {item.version_id for item in scene.agreements}
        if acceptance.scene_revision != scene.revision or set(acceptance.version_ids) != expected:
            raise CustomException(msg="协议已更新，请重新阅读并确认", status_code=409)
        self.db.add(
            AgreementAcceptanceModel(
                app_id=self.app_id, user_id=user_id, scene_code=scene.code, scene_revision=scene.revision, version_ids=[item.version_id for item in scene.agreements], business_ref=business_ref
            )
        )
        await self.db.flush()
