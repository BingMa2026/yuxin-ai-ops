from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.base_schema import JWTOutSchema


class LoginOutSchema(JWTOutSchema):
    """登录响应"""

    user_info: dict[str, Any] = Field(default_factory=dict, description="用户信息")


# =================================================== #
# *************** 微信小程序登录 Schema *************** #
# =================================================== #


class WxLoginSchema(BaseModel):
    """微信小程序登录请求（code2Session）"""

    code: str = Field(..., min_length=1, description="uni.login 返回的临时登录凭证 code")
    nickname: str | None = Field(default=None, max_length=64, description="用户昵称（来自 getUserProfile，可选）")
    avatar: str | None = Field(default=None, max_length=512, description="头像 URL（可选）")


class WxPhoneLoginSchema(BaseModel):
    """微信小程序手机号登录请求"""

    code: str = Field(..., min_length=1, description="getPhoneNumber 回调返回的动态令牌 code")


class WxQrCodeSchema(BaseModel):
    """小程序码生成请求"""

    scene: str = Field(..., max_length=32, description="场景参数（如 invite=xxx，最大32字符）")
    page: str | None = Field(default=None, max_length=128, description="小程序页面路径（如 pages/index/index），为空则默认主页")
    width: int = Field(default=430, ge=280, le=1280, description="小程序码宽度（px）")


class WxQrCodeOutSchema(BaseModel):
    """小程序码生成响应"""

    model_config = ConfigDict(from_attributes=True)

    url: str = Field(..., description="小程序码图片 URL（已上传 OSS / 本地文件路径）")
