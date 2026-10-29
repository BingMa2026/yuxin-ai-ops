from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema, PageResultSchema
from app.core.exceptions import CustomException

from .crud import lock_app, scoped_row
from .model import AgreementAcceptanceModel, AgreementModel, AgreementSceneModel, AgreementVersionModel
from .schema import REQUIRED_SCENES, AcceptanceOut, AgreementOut, DraftInput, SceneInput, SceneOut, VersionOut, has_text


class AgreementService:
    def __init__(self, auth: AuthSchema, db: AsyncSession):
        if not auth.app_id:
            raise CustomException(msg="请先选择客户端", status_code=409)
        self.app_id = auth.app_id
        self.operator_id = auth.user.id
        self.db = db

    async def list(self, kind: str, page_no: int, page_size: int, keyword: str = "", status: str | None = None, has_draft: bool | None = None):
        model = AgreementModel if kind == "agreements" else AgreementSceneModel
        schema = AgreementOut if kind == "agreements" else SceneOut
        stmt = select(model).where(model.app_id == self.app_id, model.is_deleted == False)
        if keyword:
            title = model.title if kind == "agreements" else model.name
            stmt = stmt.where(or_(title.icontains(keyword, autoescape=True), model.code.icontains(keyword, autoescape=True)))
        if kind == "agreements":
            if status:
                stmt = stmt.where(model.status == status)
            if has_draft is not None:
                stmt = stmt.where(model.has_draft == has_draft)
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (await self.db.scalars(stmt.order_by(model.updated_time.desc(), model.id.desc()).offset((page_no - 1) * page_size).limit(page_size))).all()
        return PageResultSchema(page_no=page_no, page_size=page_size, total=total, has_next=page_no * page_size < total, items=[schema.model_validate(row) for row in rows])

    @staticmethod
    def check_revision(row, revision: int):
        if row.revision != revision:
            raise CustomException(msg="内容已被其他操作更新，请重新打开后编辑；当前输入请先保留", status_code=409)

    async def detail(self, row_id: int):
        return AgreementOut.model_validate(await scoped_row(self.db, AgreementModel, self.app_id, row_id))

    async def save(self, data: DraftInput, row_id: int | None = None):
        await lock_app(self.db, self.app_id)
        row = await scoped_row(self.db, AgreementModel, self.app_id, row_id) if row_id else None
        if row:
            self.check_revision(row, data.revision)
            if row.status == "archived":
                raise CustomException(msg="请先恢复归档协议", status_code=400)
            if row.current_version and data.code != row.code:
                raise CustomException(msg="已发布协议的标识不能修改", status_code=400)
        duplicate = await self.db.scalar(select(AgreementModel.id).where(AgreementModel.app_id == self.app_id, AgreementModel.code == data.code, AgreementModel.id != (row_id or 0)))
        if duplicate:
            raise CustomException(msg="当前客户端已使用该协议标识，请使用其他标识", status_code=409)
        if row is None:
            row = AgreementModel(app_id=self.app_id, revision=1)
            self.db.add(row)
        else:
            row.revision += 1
        for key, value in data.model_dump(exclude={"revision"}).items():
            setattr(row, key, value)
        row.has_draft = True
        row.updated_by = self.operator_id
        await self.db.flush()
        return AgreementOut.model_validate(row)

    async def publish(self, row_id: int, revision: int):
        await lock_app(self.db, self.app_id)
        row = await scoped_row(self.db, AgreementModel, self.app_id, row_id)
        self.check_revision(row, revision)
        if row.status == "archived" or not row.has_draft:
            raise CustomException(msg="没有可发布的草稿", status_code=400)
        if not has_text(row.content) or not row.change_summary.strip():
            raise CustomException(msg="发布前请填写正文和更新说明", status_code=400)
        row.current_version += 1
        row.revision += 1
        row.has_draft = False
        row.status = "published"
        row.updated_by = self.operator_id
        self.db.add(
            AgreementVersionModel(
                app_id=self.app_id,
                agreement_id=row.id,
                version=row.current_version,
                title=row.title,
                content=row.content,
                change_summary=row.change_summary,
                published_at=datetime.now(UTC),
                published_by=self.operator_id,
            )
        )
        await self.db.flush()
        return AgreementOut.model_validate(row)

    async def history(self, row_id: int):
        await scoped_row(self.db, AgreementModel, self.app_id, row_id)
        rows = (
            await self.db.scalars(
                select(AgreementVersionModel).where(AgreementVersionModel.app_id == self.app_id, AgreementVersionModel.agreement_id == row_id).order_by(AgreementVersionModel.version.desc())
            )
        ).all()
        return [VersionOut.model_validate(row) for row in rows]

    async def restore_version(self, row_id: int, version_id: int, revision: int):
        await lock_app(self.db, self.app_id)
        row = await scoped_row(self.db, AgreementModel, self.app_id, row_id)
        self.check_revision(row, revision)
        version = await self.db.scalar(
            select(AgreementVersionModel).where(AgreementVersionModel.app_id == self.app_id, AgreementVersionModel.agreement_id == row_id, AgreementVersionModel.id == version_id)
        )
        if not version or row.status == "archived":
            raise CustomException(msg="版本不存在或协议已归档", status_code=400)
        row.title, row.content = version.title, version.content
        row.change_summary = f"基于 V{version.version} 恢复内容"
        row.has_draft = True
        row.revision += 1
        row.updated_by = self.operator_id
        await self.db.flush()
        return AgreementOut.model_validate(row)

    async def remove(self, row_id: int, revision: int, *, archive: bool = False):
        await lock_app(self.db, self.app_id)
        row = await scoped_row(self.db, AgreementModel, self.app_id, row_id)
        self.check_revision(row, revision)
        scenes = (await self.db.scalars(select(AgreementSceneModel).where(AgreementSceneModel.app_id == self.app_id, AgreementSceneModel.is_deleted == False))).all()
        if any(row_id in scene.agreement_ids for scene in scenes):
            raise CustomException(msg="协议仍被使用场景引用，请先替换或解除关联", status_code=409)
        if not archive and row.current_version:
            raise CustomException(msg="已发布协议请使用归档，历史版本不能删除", status_code=400)
        if archive:
            row.status = "archived"
        else:
            row.is_deleted = True
            row.deleted_time = datetime.now(UTC)
        row.revision += 1
        row.updated_by = self.operator_id
        await self.db.flush()

    async def unarchive(self, row_id: int, revision: int):
        await lock_app(self.db, self.app_id)
        row = await scoped_row(self.db, AgreementModel, self.app_id, row_id)
        self.check_revision(row, revision)
        if row.status != "archived":
            raise CustomException(msg="协议未归档", status_code=400)
        # Resume as a draft; explicit publication is required to make it public again.
        row.status, row.has_draft = "draft", True
        row.revision += 1
        row.updated_by = self.operator_id
        await self.db.flush()
        return AgreementOut.model_validate(row)

    async def save_scene(self, data: SceneInput, row_id: int | None = None):
        await lock_app(self.db, self.app_id)
        row = await scoped_row(self.db, AgreementSceneModel, self.app_id, row_id) if row_id else None
        if row:
            self.check_revision(row, data.revision)
            if data.code != row.code:
                raise CustomException(msg="场景标识不能修改，请新增场景", status_code=400)
        duplicate = await self.db.scalar(
            select(AgreementSceneModel.id).where(AgreementSceneModel.app_id == self.app_id, AgreementSceneModel.code == data.code, AgreementSceneModel.id != (row_id or 0))
        )
        if duplicate:
            raise CustomException(msg="当前客户端已使用该场景标识", status_code=409)
        for agreement_id in data.agreement_ids:
            agreement = await scoped_row(self.db, AgreementModel, self.app_id, agreement_id)
            if agreement.status != "published":
                raise CustomException(msg="场景只能关联已发布协议", status_code=400)
        if row is None:
            row = AgreementSceneModel(app_id=self.app_id, revision=1)
            self.db.add(row)
        else:
            row.revision += 1
        for key, value in data.model_dump(exclude={"revision"}).items():
            setattr(row, key, value)
        row.updated_by = self.operator_id
        await self.db.flush()
        return SceneOut.model_validate(row)

    async def delete_scene(self, row_id: int, revision: int):
        await lock_app(self.db, self.app_id)
        row = await scoped_row(self.db, AgreementSceneModel, self.app_id, row_id)
        self.check_revision(row, revision)
        if row.code in REQUIRED_SCENES:
            raise CustomException(msg="已接入的注册和购买场景不能删除，请替换关联协议", status_code=400)
        row.is_deleted = True
        row.deleted_time = datetime.now(UTC)
        row.revision += 1
        await self.db.flush()

    async def acceptances(self, page_no: int, page_size: int, user_id: int | None = None):
        stmt = select(AgreementAcceptanceModel).where(AgreementAcceptanceModel.app_id == self.app_id)
        if user_id:
            stmt = stmt.where(AgreementAcceptanceModel.user_id == user_id)
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (await self.db.scalars(stmt.order_by(AgreementAcceptanceModel.id.desc()).offset((page_no - 1) * page_size).limit(page_size))).all()
        return PageResultSchema(page_no=page_no, page_size=page_size, total=total, has_next=page_no * page_size < total, items=[AcceptanceOut.model_validate(row) for row in rows])
