from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Security
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PageResultSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .public_service import PublicAgreementService
from .schema import AcceptanceOut, AgreementOut, DraftInput, PublicAgreement, PublicScene, RevisionInput, SceneInput, SceneOut, VersionOut
from .service import AgreementService

agreement_admin_router = APIRouter(prefix="/operations/agreements", tags=["协议与政策"], route_class=OperationLogRoute)
agreement_public_router = APIRouter(prefix="/public/client-apps/{app_code}", tags=["客户端公开协议"])
DB = Annotated[AsyncSession, Depends(db_getter)]
Reader = Annotated[AuthSchema, Security(AuthPermission(["workspace:user:agreement:list"]))]
Editor = Annotated[AuthSchema, Security(AuthPermission(["workspace:user:agreement:update"]))]
Publisher = Annotated[AuthSchema, Security(AuthPermission(["workspace:user:agreement:publish"]))]
Deleter = Annotated[AuthSchema, Security(AuthPermission(["workspace:user:agreement:delete"]))]
SceneEditor = Annotated[AuthSchema, Security(AuthPermission(["workspace:user:agreement:scene"]))]
Page = Annotated[PaginationQueryParam, Depends()]


@agreement_admin_router.get("", response_model=ResponseSchema[PageResultSchema[AgreementOut]])
async def agreements(auth: Reader, db: DB, page: Page, keyword: str = "", status: Literal["draft", "published", "archived"] | None = None, has_draft: bool | None = None):
    return SuccessResponse(data=await AgreementService(auth, db).list("agreements", page.page_no, page.page_size, keyword, status, has_draft))


@agreement_admin_router.post("", response_model=ResponseSchema[AgreementOut])
async def create(data: DraftInput, auth: Editor, db: DB):
    return SuccessResponse(data=await AgreementService(auth, db).save(data), msg="草稿已保存")


@agreement_admin_router.get("/scenes", response_model=ResponseSchema[PageResultSchema[SceneOut]])
async def scenes(auth: Reader, db: DB, page: Page, keyword: str = ""):
    return SuccessResponse(data=await AgreementService(auth, db).list("scenes", page.page_no, page.page_size, keyword))


@agreement_admin_router.post("/scenes", response_model=ResponseSchema[SceneOut])
async def create_scene(data: SceneInput, auth: SceneEditor, db: DB):
    return SuccessResponse(data=await AgreementService(auth, db).save_scene(data), msg="场景配置已生效")


@agreement_admin_router.put("/scenes/{row_id}", response_model=ResponseSchema[SceneOut])
async def update_scene(row_id: int, data: SceneInput, auth: SceneEditor, db: DB):
    return SuccessResponse(data=await AgreementService(auth, db).save_scene(data, row_id), msg="场景配置已生效")


@agreement_admin_router.delete("/scenes/{row_id}", response_model=ResponseSchema[None])
async def delete_scene(row_id: int, auth: Deleter, db: DB, revision: Annotated[int, Query(ge=1)]):
    await AgreementService(auth, db).delete_scene(row_id, revision)
    return SuccessResponse(msg="场景已删除")


@agreement_admin_router.get("/acceptances", response_model=ResponseSchema[PageResultSchema[AcceptanceOut]])
async def acceptances(auth: Reader, db: DB, page: Page, user_id: int | None = None):
    return SuccessResponse(data=await AgreementService(auth, db).acceptances(page.page_no, page.page_size, user_id))


@agreement_admin_router.get("/{row_id}", response_model=ResponseSchema[AgreementOut])
async def detail(row_id: int, auth: Reader, db: DB):
    return SuccessResponse(data=await AgreementService(auth, db).detail(row_id))


@agreement_admin_router.put("/{row_id}", response_model=ResponseSchema[AgreementOut])
async def update(row_id: int, data: DraftInput, auth: Editor, db: DB):
    return SuccessResponse(data=await AgreementService(auth, db).save(data, row_id), msg="草稿已保存")


@agreement_admin_router.post("/{row_id}/publish", response_model=ResponseSchema[AgreementOut])
async def publish(row_id: int, data: RevisionInput, auth: Publisher, db: DB):
    return SuccessResponse(data=await AgreementService(auth, db).publish(row_id, data.revision), msg="协议已发布")


@agreement_admin_router.post("/{row_id}/archive", response_model=ResponseSchema[None])
async def archive(row_id: int, data: RevisionInput, auth: Publisher, db: DB):
    await AgreementService(auth, db).remove(row_id, data.revision, archive=True)
    return SuccessResponse(msg="协议已归档")


@agreement_admin_router.post("/{row_id}/unarchive", response_model=ResponseSchema[AgreementOut])
async def unarchive(row_id: int, data: RevisionInput, auth: Editor, db: DB):
    return SuccessResponse(data=await AgreementService(auth, db).unarchive(row_id, data.revision), msg="已恢复为草稿，请检查后重新发布")


@agreement_admin_router.delete("/{row_id}", response_model=ResponseSchema[None])
async def delete(row_id: int, auth: Deleter, db: DB, revision: Annotated[int, Query(ge=1)]):
    await AgreementService(auth, db).remove(row_id, revision)
    return SuccessResponse(msg="草稿已删除")


@agreement_admin_router.get("/{row_id}/versions", response_model=ResponseSchema[list[VersionOut]])
async def history(row_id: int, auth: Reader, db: DB):
    return SuccessResponse(data=await AgreementService(auth, db).history(row_id))


@agreement_admin_router.post("/{row_id}/versions/{version_id}/restore", response_model=ResponseSchema[AgreementOut])
async def restore(row_id: int, version_id: int, data: RevisionInput, auth: Editor, db: DB):
    return SuccessResponse(data=await AgreementService(auth, db).restore_version(row_id, version_id, data.revision), msg="已复制为新草稿")


@agreement_public_router.get("/agreements/{code}", response_model=ResponseSchema[PublicAgreement])
async def public_agreement(app_code: str, code: str, db: DB):
    service = await PublicAgreementService.for_code(db, app_code)
    response = SuccessResponse(data=await service.agreement(code))
    response.headers["Cache-Control"] = "no-store"
    return response


@agreement_public_router.get("/agreement-scenes/{code}", response_model=ResponseSchema[PublicScene])
async def public_scene(app_code: str, code: str, db: DB):
    service = await PublicAgreementService.for_code(db, app_code)
    response = SuccessResponse(data=await service.scene(code))
    response.headers["Cache-Control"] = "no-store"
    return response
