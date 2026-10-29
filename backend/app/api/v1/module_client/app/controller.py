from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, Path, Query, Security, UploadFile, status
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PageResultSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import (
    ClientAppCreateSchema,
    ClientAppOutSchema,
    ClientAppQueryParam,
    ClientAppStaffGrantSchema,
    ClientAppStaffOptionSchema,
    ClientAppUpdateSchema,
    ClientReleaseArtifactCreateSchema,
    ClientReleaseCreateSchema,
    ClientReleaseOutSchema,
    ClientReleaseUpdateSchema,
)
from .service import ClientAppService, ClientReleaseService

ClientAppRouter = APIRouter(route_class=OperationLogRoute, prefix="/client-apps", tags=["客户端应用"])
ClientUpdatePublicRouter = APIRouter(prefix="/public/client-apps", tags=["客户端更新"])


@ClientAppRouter.get("/list", response_model=ResponseSchema[PageResultSchema[ClientAppOutSchema]], summary="客户端应用列表")
async def list_client_apps(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:product:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[ClientAppQueryParam, Query()],
) -> JSONResponse:
    result = await ClientAppService(auth, db).page(page.page_no, page.page_size, search, page.order_by)
    return SuccessResponse(data=result, msg="查询客户端成功")


@ClientAppRouter.get("/switchable", response_model=ResponseSchema[list[ClientAppOutSchema]], summary="可切换客户端")
async def switchable_client_apps(
    auth: Annotated[AuthSchema, Security(AuthPermission())],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    return SuccessResponse(data=await ClientAppService(auth, db).switchable(), msg="查询可切换客户端成功")


@ClientAppRouter.get("/{app_id}", response_model=ResponseSchema[ClientAppOutSchema], summary="客户端详情")
async def get_client_app(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:product:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(data=await ClientAppService(auth, db).detail(app_id))


@ClientAppRouter.post("", status_code=status.HTTP_201_CREATED, response_model=ResponseSchema[ClientAppOutSchema], summary="新增客户端")
async def create_client_app(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:product:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[ClientAppCreateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(
        data=await ClientAppService(auth, db).create(data),
        msg="新增客户端成功",
        status_code=status.HTTP_201_CREATED,
    )


@ClientAppRouter.put("/{app_id}", response_model=ResponseSchema[ClientAppOutSchema], summary="编辑客户端")
async def update_client_app(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:product:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_id: Annotated[int, Path(gt=0)],
    data: Annotated[ClientAppUpdateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ClientAppService(auth, db).update(app_id, data), msg="编辑客户端成功")


@ClientAppRouter.put("/{app_id}/staff", response_model=ResponseSchema[None], summary="配置运营人员权限")
async def grant_client_app_staff(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:product:grant"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_id: Annotated[int, Path(gt=0)],
    data: Annotated[ClientAppStaffGrantSchema, Body()],
) -> JSONResponse:
    await ClientAppService(auth, db).set_staff(app_id, data)
    return SuccessResponse(msg="客户端权限配置成功")


@ClientAppRouter.get(
    "/{app_id}/staff",
    response_model=ResponseSchema[list[ClientAppStaffOptionSchema]],
    summary="查询客户端运营人员",
)
async def get_client_app_staff(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:product:grant"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(
        data=await ClientAppService(auth, db).staff_options(app_id),
        msg="查询客户端运营人员成功",
    )


@ClientAppRouter.get("/{app_id}/releases", response_model=ResponseSchema[list[ClientReleaseOutSchema]], summary="版本列表")
async def list_client_releases(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:product:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(data=await ClientReleaseService(auth, db).list(app_id))


@ClientAppRouter.post("/{app_id}/releases", response_model=ResponseSchema[ClientReleaseOutSchema], status_code=status.HTTP_201_CREATED, summary="创建版本草稿")
async def create_client_release(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:product:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_id: Annotated[int, Path(gt=0)],
    data: Annotated[ClientReleaseCreateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ClientReleaseService(auth, db).create(app_id, data), status_code=status.HTTP_201_CREATED)


@ClientAppRouter.put("/{app_id}/releases/{release_id}", response_model=ResponseSchema[ClientReleaseOutSchema], summary="编辑版本草稿")
async def update_client_release(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:product:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_id: Annotated[int, Path(gt=0)],
    release_id: Annotated[int, Path(gt=0)],
    data: Annotated[ClientReleaseUpdateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ClientReleaseService(auth, db).update(app_id, release_id, data))


@ClientAppRouter.put("/{app_id}/releases/{release_id}/external-artifact", response_model=ResponseSchema[ClientReleaseOutSchema], summary="配置外链制品")
async def save_external_release_artifact(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:product:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_id: Annotated[int, Path(gt=0)],
    release_id: Annotated[int, Path(gt=0)],
    data: Annotated[ClientReleaseArtifactCreateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ClientReleaseService(auth, db).save_external_artifact(app_id, release_id, data))


@ClientAppRouter.post("/{app_id}/releases/{release_id}/upload", response_model=ResponseSchema[ClientReleaseOutSchema], summary="上传版本制品")
async def upload_release_artifact(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:product:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_id: Annotated[int, Path(gt=0)],
    release_id: Annotated[int, Path(gt=0)],
    artifact_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    sha512: Annotated[str | None, Form()] = None,
    signature_verified: Annotated[bool, Form()] = False,
    storage_source_id: Annotated[int | None, Form()] = None,
) -> JSONResponse:
    data = await ClientReleaseService(auth, db).save_uploaded_artifact(app_id, release_id, artifact_type, file, sha512, signature_verified, storage_source_id)
    return SuccessResponse(data=data, msg="制品上传成功")


@ClientAppRouter.post("/{app_id}/releases/{release_id}/publish", response_model=ResponseSchema[ClientReleaseOutSchema], summary="发布版本")
async def publish_client_release(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:product:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_id: Annotated[int, Path(gt=0)],
    release_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(data=await ClientReleaseService(auth, db).publish(app_id, release_id), msg="版本发布成功")


@ClientAppRouter.post("/{app_id}/releases/{release_id}/withdraw", response_model=ResponseSchema[ClientReleaseOutSchema], summary="撤回版本")
async def withdraw_client_release(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:product:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_id: Annotated[int, Path(gt=0)],
    release_id: Annotated[int, Path(gt=0)],
) -> JSONResponse:
    return SuccessResponse(data=await ClientReleaseService(auth, db).withdraw(app_id, release_id), msg="版本已撤回")


@ClientUpdatePublicRouter.get("/{app_code}/updates/windows/x64/{channel}/latest.yml", summary="electron-updater 更新清单")
async def latest_windows_release(
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_code: str,
    channel: str,
) -> PlainTextResponse:
    if channel not in {"stable", "test"}:
        return PlainTextResponse("暂无可用更新", status_code=404)
    release, artifact = await ClientReleaseService(None, db).latest(app_code, channel)
    url = artifact.external_url or f"/public/client-apps/{app_code}/updates/artifacts/{artifact.id}"
    notes = release.release_notes.replace("\r", "").replace("\n", "\\n")
    content = (
        f"version: {release.version}\n"
        f"files:\n  - url: {url}\n    sha512: {artifact.sha512}\n    size: {artifact.file_size}\n"
        f"path: {url}\nsha512: {artifact.sha512}\nreleaseDate: '{release.published_at.isoformat()}'\n"
        f'releaseNotes: "{notes.replace(chr(34), chr(39))}"\n'
    )
    return PlainTextResponse(content, media_type="text/yaml; charset=utf-8")


@ClientUpdatePublicRouter.get("/{app_code}/updates/artifacts/{artifact_id}", summary="下载更新制品")
async def download_release_artifact(
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_code: str,
    artifact_id: Annotated[int, Path(gt=0)],
) -> RedirectResponse:
    from sqlalchemy import select

    from app.api.v1.module_client.app.model import ClientAppModel, ClientAppReleaseArtifactModel, ClientAppReleaseModel

    artifact = await db.scalar(
        select(ClientAppReleaseArtifactModel)
        .join(ClientAppReleaseModel, ClientAppReleaseModel.id == ClientAppReleaseArtifactModel.release_id)
        .join(ClientAppModel, ClientAppModel.id == ClientAppReleaseModel.app_id)
        .where(
            ClientAppModel.code == app_code,
            ClientAppReleaseModel.status == "published",
            ClientAppReleaseArtifactModel.id == artifact_id,
            ClientAppReleaseArtifactModel.is_deleted == False,
        )
    )
    if not artifact:
        from app.core.exceptions import CustomException

        raise CustomException(msg="制品不存在", status_code=404)
    target_url = artifact.external_url
    if not target_url and artifact.storage_path:
        from app.api.v1.module_storage.core.factory import StorageAdapterFactory
        from app.api.v1.module_storage.source.model import StorageSourceModel
        from app.api.v1.module_storage.source.service import StorageSourceService

        source_stmt = select(StorageSourceModel).where(StorageSourceModel.status == 0, StorageSourceModel.is_deleted == False)
        if artifact.storage_source_id:
            source_stmt = source_stmt.where(StorageSourceModel.id == artifact.storage_source_id)
        else:
            source_stmt = source_stmt.order_by(StorageSourceModel.is_default.desc(), StorageSourceModel.id.asc())
        source = await db.scalar(source_stmt)
        if source:
            adapter = StorageAdapterFactory.create(StorageSourceService._build_config(source))
            try:
                target_url = await adapter.get_url(artifact.storage_path, expire=900)
            finally:
                await adapter.close()
    if not target_url:
        from app.core.exceptions import CustomException

        raise CustomException(msg="制品存储不可用", status_code=503)
    return RedirectResponse(target_url, status_code=307)
