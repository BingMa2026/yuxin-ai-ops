from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import AppScopedCRUDBase
from app.core.base_schema import AuthSchema

from .model import ClientUserModel, ClientUserTagModel
from .schema import ClientUserAdminUpdateSchema, ClientUserRegisterSchema, ClientUserTagCreateSchema


class ClientUserCRUD(AppScopedCRUDBase[ClientUserModel, ClientUserRegisterSchema, ClientUserAdminUpdateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(ClientUserModel, auth, db)


class ClientUserTagCRUD(AppScopedCRUDBase[ClientUserTagModel, ClientUserTagCreateSchema, dict]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(ClientUserTagModel, auth, db)
