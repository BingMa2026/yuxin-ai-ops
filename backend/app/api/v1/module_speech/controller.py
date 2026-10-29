from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Security, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.client_dependencies import get_current_client_user
from app.core.dependencies import AuthPermission, db_getter
from app.core.exceptions import CustomException

from .provider import MAX_AUDIO_BYTES
from .schema import SpeechCapability, SpeechConfigInput, SpeechConfigOut, SpeechModelOption, SpeechResult
from .service import SpeechService

speech_admin_router = APIRouter(prefix="/operations/models/speech", tags=["客户端语音配置"])
speech_client_router = APIRouter(prefix="/client/speech", tags=["客户端语音输入"])
DB = Annotated[AsyncSession, Depends(db_getter)]
Reader = Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:list"]))]
Editor = Annotated[AuthSchema, Security(AuthPermission(["workspace:resource:model:edit"]))]
Client = Annotated[AuthSchema, Depends(get_current_client_user)]


@speech_admin_router.get("/config", response_model=ResponseSchema[SpeechConfigOut])
async def config(auth: Reader, db: DB):
    return SuccessResponse(data=await SpeechService(auth, db).config())


@speech_admin_router.put("/config", response_model=ResponseSchema[SpeechConfigOut])
async def save(data: SpeechConfigInput, auth: Editor, db: DB):
    return SuccessResponse(data=await SpeechService(auth, db).save(data), msg="语音配置已保存")


@speech_admin_router.get("/models", response_model=ResponseSchema[list[SpeechModelOption]])
async def options(auth: Reader, db: DB):
    return SuccessResponse(data=await SpeechService(auth, db).options())


@speech_client_router.get("/capability", response_model=ResponseSchema[SpeechCapability])
async def capability(auth: Client, db: DB):
    response = SuccessResponse(data=await SpeechService(auth, db).capability())
    response.headers["Cache-Control"] = "no-store"
    return response


@speech_client_router.post("/transcriptions", response_model=ResponseSchema[SpeechResult])
async def transcriptions(auth: Client, db: DB, audio: Annotated[UploadFile, File()], request_id: Annotated[str, Form(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9-]+$")]):
    try:
        data = await audio.read(MAX_AUDIO_BYTES + 1)
    finally:
        await audio.close()
    if len(data) > MAX_AUDIO_BYTES:
        raise CustomException(msg="录音过大，请缩短录音后重试", status_code=413)
    response = SuccessResponse(data=await SpeechService(auth, db).transcribe(data, request_id))
    response.headers["Cache-Control"] = "no-store"
    return response
