from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import CRUDBase
from app.core.base_schema import AuthSchema

from .model import WorkspaceModuleModel
from .schema import WorkspaceModuleCreateSchema, WorkspaceModuleUpdateSchema


class WorkspaceModuleCRUD(CRUDBase[WorkspaceModuleModel, WorkspaceModuleCreateSchema, WorkspaceModuleUpdateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=WorkspaceModuleModel, auth=auth, db=db)
