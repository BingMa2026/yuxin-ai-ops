from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_client.app.model import ClientAppModel
from app.core.exceptions import CustomException

from .model import AgreementModel, AgreementSceneModel


async def lock_app(db: AsyncSession, app_id: int) -> None:
    # A consistent per-app lock serializes publication, scene edits and acceptance.
    app = await db.scalar(select(ClientAppModel).where(ClientAppModel.id == app_id, ClientAppModel.is_deleted == False).with_for_update())
    if not app:
        raise CustomException(msg="客户端不存在", status_code=404)


async def scoped_row(db: AsyncSession, model: type[AgreementModel] | type[AgreementSceneModel], app_id: int, row_id: int):
    row = await db.scalar(select(model).where(model.app_id == app_id, model.id == row_id, model.is_deleted == False))
    if not row:
        raise CustomException(msg="记录不存在", status_code=404)
    return row
