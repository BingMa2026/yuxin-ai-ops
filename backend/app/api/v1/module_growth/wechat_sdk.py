"""Official-account JS-SDK signatures with a shared ticket cache."""

import hashlib
import secrets
import time
from urllib.parse import parse_qs, urlsplit

import httpx

from app.config.setting import settings
from app.core.exceptions import CustomException


async def sdk_signature(redis, page_url: str, token: str) -> dict:
    url, base = urlsplit(page_url), urlsplit(settings.GROWTH_PUBLIC_BASE_URL)
    query = parse_qs(url.query)
    if (
        url.scheme != "https"
        or url.netloc != base.netloc
        or url.path != "/payout/wechat"
        or url.fragment
        or url.username
        or set(query) - {"code", "state"}
        or (query.get("state") and query["state"] != [token])
    ):
        raise CustomException(msg="微信收款页面地址无效", status_code=422)
    if redis is None:
        raise CustomException(msg="微信签名缓存服务不可用，请稍后重新扫码", status_code=503)
    key = f"growth:wechat:jsapi:{settings.GROWTH_WECHAT_APP_ID}"
    ticket = await redis.get(key)
    if not ticket:
        async with redis.lock(key + ":lock", timeout=30, blocking_timeout=5):
            ticket = await redis.get(key)
            if not ticket:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(
                        "https://api.weixin.qq.com/cgi-bin/token", params={"grant_type": "client_credential", "appid": settings.GROWTH_WECHAT_APP_ID, "secret": settings.GROWTH_WECHAT_APP_SECRET}
                    )
                    access = response.json()
                    if response.status_code != 200 or not access.get("access_token"):
                        raise CustomException(msg="微信公众号令牌获取失败，请核查商户配置", status_code=502)
                    response = await client.get("https://api.weixin.qq.com/cgi-bin/ticket/getticket", params={"access_token": access["access_token"], "type": "jsapi"})
                    data = response.json()
                if response.status_code != 200 or data.get("errcode") != 0 or not data.get("ticket"):
                    raise CustomException(msg="微信收款组件签名暂不可用", status_code=502)
                ticket = data["ticket"]
                await redis.set(key, ticket, ex=max(60, min(7000, int(data.get("expires_in", 7200)) - 200)))
    nonce, timestamp = secrets.token_hex(16), int(time.time())
    signature = hashlib.sha1(f"jsapi_ticket={ticket}&noncestr={nonce}&timestamp={timestamp}&url={page_url}".encode()).hexdigest()
    return {"appId": settings.GROWTH_WECHAT_APP_ID, "timestamp": timestamp, "nonceStr": nonce, "signature": signature}
