import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from app.config.setting import settings
from app.core.exceptions import CustomException


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_settings(value: dict) -> str:
    return _fernet().encrypt(json.dumps(value, ensure_ascii=False).encode("utf-8")).decode("utf-8")


def decrypt_settings(value: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(value.encode("utf-8")).decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise CustomException(msg="模型供应商密钥解密失败，请检查服务端密钥配置") from exc
