from pydantic import BaseModel, Field

from app.core.base_schema import SessionInfoSchema


class OnlineOutSchema(SessionInfoSchema):
    """在线用户响应模型 — ``SessionInfoSchema`` 的公开子集。"""


class OnlineQueryParam(BaseModel):
    """在线用户查询参数"""

    name: str | None = Field(None, description="登录名称")
    ipaddr: str | None = Field(None, description="登陆IP地址")
    login_location: str | None = Field(None, description="登录所属地")
