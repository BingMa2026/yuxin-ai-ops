from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import CRUDBase
from app.core.base_schema import AuthSchema

from .model import PaymentChannelModel
from .schema import PaymentChannelUpdateSchema


class PaymentChannelCRUD(CRUDBase[PaymentChannelModel, PaymentChannelUpdateSchema, PaymentChannelUpdateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=PaymentChannelModel, auth=auth, db=db)
