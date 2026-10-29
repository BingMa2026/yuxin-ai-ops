from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import UploadFile
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_storage.file.service import StorageFileService
from app.api.v1.module_system.user.model import UserModel
from app.core.base_schema import AuthSchema, PageResultSchema
from app.core.exceptions import CustomException
from app.utils.common_util import search_to_dict

from .crud import ClientAppCRUD
from .model import ClientAppModel, ClientAppReleaseArtifactModel, ClientAppReleaseModel, StaffAppModel
from .schema import (
    ClientAppCreateSchema,
    ClientAppOutSchema,
    ClientAppQueryParam,
    ClientAppStaffGrantSchema,
    ClientAppStaffOptionSchema,
    ClientAppUpdateSchema,
    ClientReleaseArtifactCreateSchema,
    ClientReleaseArtifactOutSchema,
    ClientReleaseCreateSchema,
    ClientReleaseOutSchema,
    ClientReleaseUpdateSchema,
)


class ClientAppService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    def _access_condition(self):
        if self.auth.user.is_superuser:
            return None
        return ClientAppModel.id.in_(
            select(StaffAppModel.app_id).where(
                StaffAppModel.staff_id == self.auth.user.id,
                StaffAppModel.status == "active",
                StaffAppModel.is_deleted == False,
            )
        )

    async def page(
        self,
        page_no: int,
        page_size: int,
        search: ClientAppQueryParam,
        order_by: list[dict[str, str]],
    ) -> PageResultSchema[ClientAppOutSchema]:
        query = search_to_dict(search)
        crud = ClientAppCRUD(self.auth, self.db)
        stmt = select(ClientAppModel).where(ClientAppModel.is_deleted == False)
        condition = self._access_condition()
        if condition is not None:
            stmt = stmt.where(condition)
        for key, value in query.items():
            if value is None or value == "":
                continue
            attr = getattr(ClientAppModel, key)
            if isinstance(value, tuple):
                stmt = stmt.where(*crud._resolve_condition(attr, value))
            else:
                stmt = stmt.where(attr == value)
        total = int(await self.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
        effective_order = [{"order": "asc"}, {"id": "asc"}] if order_by == [{"id": "asc"}] else order_by
        rows = list((await self.db.scalars(stmt.order_by(*crud._parse_order(effective_order)).offset((page_no - 1) * page_size).limit(page_size))).all())
        items = [ClientAppOutSchema.model_validate(row) for row in rows]
        for item in items:
            item.is_current = item.id == self.auth.app_id
        return PageResultSchema(page_no=page_no, page_size=page_size, total=total, has_next=page_no * page_size < total, items=items)

    async def switchable(self) -> list[ClientAppOutSchema]:
        stmt = select(ClientAppModel).where(ClientAppModel.is_deleted == False, ClientAppModel.status == "active")
        condition = self._access_condition()
        if condition is not None:
            stmt = stmt.where(condition)
        apps = list((await self.db.scalars(stmt.order_by(ClientAppModel.order.asc(), ClientAppModel.id.asc()))).all())
        result = [ClientAppOutSchema.model_validate(app) for app in apps]
        for item in result:
            item.is_current = item.id == self.auth.app_id
        return result

    async def detail(self, app_id: int) -> ClientAppOutSchema:
        app = await self.require_access(app_id, active_only=False)
        result = ClientAppOutSchema.model_validate(app)
        result.is_current = result.id == self.auth.app_id
        return result

    async def require_access(self, app_id: int, *, active_only: bool = True) -> ClientAppModel:
        stmt = select(ClientAppModel).where(ClientAppModel.id == app_id, ClientAppModel.is_deleted == False)
        if active_only:
            stmt = stmt.where(ClientAppModel.status == "active")
        condition = self._access_condition()
        if condition is not None:
            stmt = stmt.where(condition)
        app = await self.db.scalar(stmt)
        if not app:
            raise CustomException(msg="客户端不存在、已停用或无访问权限", status_code=403)
        return app

    async def create(self, data: ClientAppCreateSchema) -> ClientAppOutSchema:
        if await ClientAppCRUD(self.auth, self.db).get(code=data.code):
            raise CustomException(msg="应用编码已存在")
        app = await ClientAppCRUD(self.auth, self.db).create(data)
        self.db.add(StaffAppModel(staff_id=self.auth.user.id, app_id=app.id, is_default=False, status="active"))
        await self.db.flush()
        return ClientAppOutSchema.model_validate(app)

    async def update(self, app_id: int, data: ClientAppUpdateSchema) -> ClientAppOutSchema:
        await self.require_access(app_id, active_only=False)
        from .model_policy import change_model_policy, get_model_policy

        app = await get_model_policy(self.db, app_id, lock=True)
        values = data.model_dump(exclude_unset=True)
        enabled = values.pop("platform_model_enabled", None)
        expected = values.pop("expected_policy_version", None)
        mode = values.pop("service_mode", None)
        if mode is not None and mode != app.service_mode and expected is None:
            raise CustomException(msg="请刷新客户端配置后再修改服务模式", status_code=409)
        if mode is not None or enabled is not None:
            await change_model_policy(self.db, app, mode if mode is not None else enabled, expected)
        for key, value in values.items():
            setattr(app, key, value)
        app.updated_id = self.auth.user.id
        await self.db.flush()
        return ClientAppOutSchema.model_validate(app)

    async def set_staff(self, app_id: int, data: ClientAppStaffGrantSchema) -> None:
        await self.require_access(app_id, active_only=False)
        staff_ids = sorted(set(data.staff_ids))
        if staff_ids:
            actual_ids = set((await self.db.scalars(select(UserModel.id).where(UserModel.id.in_(staff_ids), UserModel.is_deleted == False))).all())
            if actual_ids != set(staff_ids):
                raise CustomException(msg="部分运营人员不存在")
        await self.db.execute(delete(StaffAppModel).where(StaffAppModel.app_id == app_id))
        self.db.add_all([StaffAppModel(staff_id=staff_id, app_id=app_id, status="active") for staff_id in staff_ids])
        await self.db.flush()

    async def staff_options(self, app_id: int) -> list[ClientAppStaffOptionSchema]:
        await self.require_access(app_id, active_only=False)
        selected_ids = set(
            (
                await self.db.scalars(
                    select(StaffAppModel.staff_id).where(
                        StaffAppModel.app_id == app_id,
                        StaffAppModel.status == "active",
                        StaffAppModel.is_deleted == False,
                    )
                )
            ).all()
        )
        staff = (await self.db.scalars(select(UserModel).where(UserModel.is_deleted == False, UserModel.status == 0).order_by(UserModel.name.asc(), UserModel.username.asc()))).all()
        return [
            ClientAppStaffOptionSchema(
                id=user.id,
                username=user.username,
                name=user.name,
                selected=user.id in selected_ids,
            )
            for user in staff
        ]

    @staticmethod
    async def resolve_default_app_id(db: AsyncSession, staff_id: int, is_superuser: bool) -> int | None:
        stmt = (
            select(ClientAppModel.id)
            .join(StaffAppModel, StaffAppModel.app_id == ClientAppModel.id)
            .where(
                StaffAppModel.staff_id == staff_id,
                StaffAppModel.status == "active",
                StaffAppModel.is_deleted == False,
                ClientAppModel.status == "active",
                ClientAppModel.is_deleted == False,
            )
            .order_by(ClientAppModel.order.asc(), ClientAppModel.id.asc())
        )
        app_id = await db.scalar(stmt)
        if app_id is not None or not is_superuser:
            return app_id
        return await db.scalar(select(ClientAppModel.id).where(ClientAppModel.status == "active", ClientAppModel.is_deleted == False).order_by(ClientAppModel.order.asc(), ClientAppModel.id.asc()))

    async def mark_default(self, app_id: int) -> None:
        await self.require_access(app_id)
        await self.db.execute(update(StaffAppModel).where(StaffAppModel.staff_id == self.auth.user.id).values(is_default=False))
        binding = await self.db.scalar(
            select(StaffAppModel).where(
                StaffAppModel.staff_id == self.auth.user.id,
                StaffAppModel.app_id == app_id,
                StaffAppModel.is_deleted == False,
            )
        )
        if binding:
            binding.is_default = True
        elif self.auth.user.is_superuser:
            self.db.add(StaffAppModel(staff_id=self.auth.user.id, app_id=app_id, is_default=True, status="active"))
        await self.db.flush()


def _version_key(version: str) -> tuple[int, int, int, str]:
    core, _, suffix = version.partition("-")
    try:
        major, minor, patch = (int(part) for part in core.split("."))
    except (TypeError, ValueError) as exc:
        raise CustomException(msg="版本号必须使用语义化版本，例如 1.2.0") from exc
    return major, minor, patch, suffix


class ClientReleaseService:
    """Windows 版本生命周期与 electron-updater Feed。"""

    def __init__(self, auth: AuthSchema | None, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def _release(self, app_id: int, release_id: int, *, draft_only: bool = False) -> ClientAppReleaseModel:
        release = await self.db.scalar(
            select(ClientAppReleaseModel).where(
                ClientAppReleaseModel.id == release_id,
                ClientAppReleaseModel.app_id == app_id,
                ClientAppReleaseModel.is_deleted == False,
            )
        )
        if not release:
            raise CustomException(msg="客户端版本不存在", status_code=404)
        if draft_only and release.status != "draft":
            raise CustomException(msg="已发布或已撤回版本不可修改")
        return release

    async def _out(self, release: ClientAppReleaseModel) -> ClientReleaseOutSchema:
        artifacts = list(
            (
                await self.db.scalars(
                    select(ClientAppReleaseArtifactModel)
                    .where(
                        ClientAppReleaseArtifactModel.release_id == release.id,
                        ClientAppReleaseArtifactModel.is_deleted == False,
                    )
                    .order_by(ClientAppReleaseArtifactModel.artifact_type.asc())
                )
            ).all()
        )
        result = ClientReleaseOutSchema.model_validate(release)
        result.artifacts = [ClientReleaseArtifactOutSchema.model_validate(item) for item in artifacts]
        return result

    async def list(self, app_id: int) -> list[ClientReleaseOutSchema]:
        if self.auth:
            await ClientAppService(self.auth, self.db).require_access(app_id, active_only=False)
        rows = list(
            (
                await self.db.scalars(select(ClientAppReleaseModel).where(ClientAppReleaseModel.app_id == app_id, ClientAppReleaseModel.is_deleted == False).order_by(ClientAppReleaseModel.id.desc()))
            ).all()
        )
        return [await self._out(row) for row in rows]

    async def create(self, app_id: int, data: ClientReleaseCreateSchema) -> ClientReleaseOutSchema:
        if not self.auth:
            raise CustomException(msg="无权执行此操作", status_code=403)
        await ClientAppService(self.auth, self.db).require_access(app_id, active_only=False)
        duplicate = await self.db.scalar(
            select(ClientAppReleaseModel.id).where(
                ClientAppReleaseModel.app_id == app_id,
                ClientAppReleaseModel.channel == data.channel,
                ClientAppReleaseModel.version == data.version,
                ClientAppReleaseModel.is_deleted == False,
            )
        )
        if duplicate:
            raise CustomException(msg="该渠道已存在相同版本号")
        release = ClientAppReleaseModel(
            app_id=app_id,
            **data.model_dump(),
            platform="windows",
            arch="x64",
            status="draft",
            created_id=self.auth.user.id,
            updated_id=self.auth.user.id,
        )
        self.db.add(release)
        await self.db.flush()
        return await self._out(release)

    async def update(self, app_id: int, release_id: int, data: ClientReleaseUpdateSchema) -> ClientReleaseOutSchema:
        release = await self._release(app_id, release_id, draft_only=True)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(release, key, value)
        release.updated_id = self.auth.user.id if self.auth else None
        await self.db.flush()
        return await self._out(release)

    async def save_external_artifact(
        self,
        app_id: int,
        release_id: int,
        data: ClientReleaseArtifactCreateSchema,
    ) -> ClientReleaseOutSchema:
        release = await self._release(app_id, release_id, draft_only=True)
        parsed = urlparse(data.external_url)
        if parsed.scheme != "https":
            raise CustomException(msg="安装制品必须使用 HTTPS 地址")
        artifact = await self.db.scalar(
            select(ClientAppReleaseArtifactModel).where(
                ClientAppReleaseArtifactModel.release_id == release_id,
                ClientAppReleaseArtifactModel.artifact_type == data.artifact_type,
                ClientAppReleaseArtifactModel.is_deleted == False,
            )
        )
        values = data.model_dump()
        values.update(source_type="external", storage_source_id=None, storage_path=None)
        if artifact:
            for key, value in values.items():
                setattr(artifact, key, value)
            artifact.updated_id = self.auth.user.id if self.auth else None
        else:
            self.db.add(
                ClientAppReleaseArtifactModel(
                    release_id=release_id,
                    **values,
                    created_id=self.auth.user.id if self.auth else None,
                    updated_id=self.auth.user.id if self.auth else None,
                )
            )
        await self.db.flush()
        return await self._out(release)

    async def save_uploaded_artifact(
        self,
        app_id: int,
        release_id: int,
        artifact_type: str,
        file: UploadFile,
        sha512: str | None,
        signature_verified: bool,
        storage_source_id: int | None,
    ) -> ClientReleaseOutSchema:
        if not self.auth:
            raise CustomException(msg="无权执行此操作", status_code=403)
        release = await self._release(app_id, release_id, draft_only=True)
        if artifact_type not in {"installer", "blockmap"}:
            raise CustomException(msg="制品类型无效")
        allowed = {".exe", ".msi", ".msix", ".blockmap"}
        remote_dir = f"client-releases/{app_id}/{release.channel}/{release.version}/"
        uploaded = await StorageFileService(self.auth, self.db).upload(
            storage_source_id,
            file,
            remote_dir,
            max_size_bytes=4 * 1024 * 1024 * 1024,
            allowed_extensions=allowed,
        )
        artifact = await self.db.scalar(
            select(ClientAppReleaseArtifactModel).where(
                ClientAppReleaseArtifactModel.release_id == release_id,
                ClientAppReleaseArtifactModel.artifact_type == artifact_type,
                ClientAppReleaseArtifactModel.is_deleted == False,
            )
        )
        values = {
            "source_type": "upload",
            "storage_source_id": storage_source_id,
            "storage_path": uploaded["file_path"],
            "external_url": None,
            "file_name": uploaded["file_name"],
            "file_size": uploaded["file_size"],
            "sha512": sha512,
            "signature_verified": signature_verified,
        }
        if artifact:
            for key, value in values.items():
                setattr(artifact, key, value)
            artifact.updated_id = self.auth.user.id
        else:
            self.db.add(
                ClientAppReleaseArtifactModel(
                    release_id=release_id,
                    artifact_type=artifact_type,
                    **values,
                    created_id=self.auth.user.id,
                    updated_id=self.auth.user.id,
                )
            )
        await self.db.flush()
        return await self._out(release)

    async def publish(self, app_id: int, release_id: int) -> ClientReleaseOutSchema:
        release = await self._release(app_id, release_id, draft_only=True)
        artifacts = (await self._out(release)).artifacts
        installer = next((item for item in artifacts if item.artifact_type == "installer"), None)
        if not installer or not installer.sha512:
            raise CustomException(msg="发布前必须配置安装包和 SHA-512")
        if release.channel == "stable" and not installer.signature_verified:
            raise CustomException(msg="正式渠道只允许发布已验证数字签名的安装包")
        latest = await self.db.scalar(
            select(ClientAppReleaseModel)
            .where(
                ClientAppReleaseModel.app_id == app_id,
                ClientAppReleaseModel.channel == release.channel,
                ClientAppReleaseModel.status == "published",
                ClientAppReleaseModel.is_deleted == False,
            )
            .order_by(ClientAppReleaseModel.published_at.desc())
        )
        if latest and _version_key(release.version) <= _version_key(latest.version):
            raise CustomException(msg=f"版本号必须高于当前已发布版本 {latest.version}")
        release.status = "published"
        release.published_at = datetime.now(UTC)
        release.updated_id = self.auth.user.id if self.auth else None
        await self.db.execute(update(ClientAppModel).where(ClientAppModel.id == app_id).values(client_version=release.version))
        await self.db.flush()
        return await self._out(release)

    async def withdraw(self, app_id: int, release_id: int) -> ClientReleaseOutSchema:
        release = await self._release(app_id, release_id)
        if release.status != "published":
            raise CustomException(msg="仅已发布版本可以撤回")
        release.status = "withdrawn"
        release.updated_id = self.auth.user.id if self.auth else None
        await self.db.flush()
        return await self._out(release)

    async def latest(self, app_code: str, channel: str) -> tuple[ClientAppReleaseModel, ClientAppReleaseArtifactModel]:
        row = (
            await self.db.execute(
                select(ClientAppReleaseModel, ClientAppReleaseArtifactModel)
                .join(ClientAppModel, ClientAppModel.id == ClientAppReleaseModel.app_id)
                .join(
                    ClientAppReleaseArtifactModel,
                    (ClientAppReleaseArtifactModel.release_id == ClientAppReleaseModel.id)
                    & (ClientAppReleaseArtifactModel.artifact_type == "installer")
                    & (ClientAppReleaseArtifactModel.is_deleted == False),
                )
                .where(
                    ClientAppModel.code == app_code,
                    ClientAppModel.status == "active",
                    ClientAppModel.is_deleted == False,
                    ClientAppReleaseModel.platform == "windows",
                    ClientAppReleaseModel.arch == "x64",
                    ClientAppReleaseModel.channel == channel,
                    ClientAppReleaseModel.status == "published",
                    ClientAppReleaseModel.is_deleted == False,
                )
                .order_by(ClientAppReleaseModel.published_at.desc())
            )
        ).first()
        if not row:
            raise CustomException(msg="暂无可用更新", status_code=404)
        return row
