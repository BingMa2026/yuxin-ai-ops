from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import CRUDBase
from app.core.base_schema import AuthSchema

from .model import ClientAppModel, StaffAppModel
from .schema import ClientAppCreateSchema, ClientAppUpdateSchema


class ClientAppCRUD(CRUDBase[ClientAppModel, ClientAppCreateSchema, ClientAppUpdateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(ClientAppModel, auth, db)


class StaffAppCRUD(CRUDBase[StaffAppModel, dict, dict]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(StaffAppModel, auth, db)
