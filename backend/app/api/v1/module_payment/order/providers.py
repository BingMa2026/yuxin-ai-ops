import base64
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config.setting import settings
from app.core.exceptions import CustomException

ALIPAY_QR_TIMEOUT_MINUTES = 15


@dataclass(frozen=True, slots=True)
class VerifiedPayment:
    callback_id: str
    order_no: str
    provider_trade_no: str
    amount_fen: int
    paid_at: datetime | None
    payload_digest: str


@dataclass(frozen=True, slots=True)
class VerifiedClosedOrder:
    order_no: str
    amount_fen: int
    previously_paid: bool = False


@dataclass(frozen=True, slots=True)
class VerifiedAbsentOrder:
    """Signed Alipay absence, distinct from an unpaid or closed trade."""

    order_no: str


def _private_key(path: str):
    return serialization.load_pem_private_key(Path(path).read_bytes(), password=None)


def _public_key(path: str):
    raw = Path(path).read_bytes()
    try:
        return x509.load_pem_x509_certificate(raw).public_key()
    except ValueError:
        return serialization.load_pem_public_key(raw)


def _rsa_sign(path: str, content: str) -> str:
    signature = _private_key(path).sign(content.encode(), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode()


def _rsa_verify(path: str, content: str, signature: str) -> None:
    try:
        _public_key(path).verify(base64.b64decode(signature), content.encode(), padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:
        raise CustomException(msg="支付回调签名校验失败", status_code=400) from exc


def _wechat_verify_path(serial: str) -> str:
    if serial.startswith("PUB_KEY_ID_"):
        if serial == settings.WECHAT_PAY_PUBLIC_KEY_ID and settings.WECHAT_PAY_PUBLIC_KEY_PATH:
            return settings.WECHAT_PAY_PUBLIC_KEY_PATH
        raise CustomException(msg="微信支付回调公钥ID不匹配", status_code=400)
    path = settings.WECHAT_PAY_PLATFORM_CERT_PATH
    try:
        certificate = x509.load_pem_x509_certificate(Path(path).read_bytes())
    except (OSError, ValueError) as exc:
        raise CustomException(msg="微信支付平台证书不可用", status_code=500) from exc
    if serial.upper() != f"{certificate.serial_number:X}":
        raise CustomException(msg="微信支付回调证书序列号不匹配", status_code=400)
    return path


def _wechat_authorization(method: str, request_target: str, body: str = "") -> str:
    timestamp = str(int(time.time()))
    nonce = uuid4().hex
    signature = _rsa_sign(
        settings.WECHAT_PAY_PRIVATE_KEY_PATH,
        f"{method}\n{request_target}\n{timestamp}\n{nonce}\n{body}\n",
    )
    return f'WECHATPAY2-SHA256-RSA2048 mchid="{settings.WECHAT_PAY_MCH_ID}",nonce_str="{nonce}",timestamp="{timestamp}",serial_no="{settings.WECHAT_PAY_MERCHANT_SERIAL_NO}",signature="{signature}"'


def _wechat_request_headers(method: str, request_target: str, body: str = "", *, json_body: bool = False) -> dict[str, str]:
    headers = {
        "Authorization": _wechat_authorization(method, request_target, body),
        "Accept": "application/json",
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    if settings.WECHAT_PAY_PUBLIC_KEY_ID and settings.WECHAT_PAY_PUBLIC_KEY_PATH:
        headers["Wechatpay-Serial"] = settings.WECHAT_PAY_PUBLIC_KEY_ID
    return headers


def _verify_wechat_signed_message(headers: dict[str, str], raw_body: bytes) -> None:
    timestamp = headers.get("wechatpay-timestamp", "")
    nonce = headers.get("wechatpay-nonce", "")
    signature = headers.get("wechatpay-signature", "")
    serial = headers.get("wechatpay-serial", "")
    try:
        timestamp_valid = bool(timestamp) and abs(int(time.time()) - int(timestamp)) <= 300
    except ValueError:
        timestamp_valid = False
    if not timestamp_valid:
        raise CustomException(msg="微信支付响应时间戳无效", status_code=400)
    _rsa_verify(
        _wechat_verify_path(serial),
        f"{timestamp}\n{nonce}\n{raw_body.decode()}\n",
        signature,
    )


def _amount_fen(value: str, provider_name: str) -> int:
    try:
        amount_decimal = Decimal(value)
        amount_fen_decimal = amount_decimal * 100
        if amount_decimal < 0 or amount_fen_decimal != amount_fen_decimal.to_integral_value():
            raise InvalidOperation
        return int(amount_fen_decimal)
    except (InvalidOperation, ValueError) as exc:
        raise CustomException(msg=f"{provider_name}金额无效", status_code=400) from exc


def _alipay_gateway(sandbox: bool) -> str:
    return "https://openapi-sandbox.dl.alipaydev.com/gateway.do" if sandbox else "https://openapi.alipay.com/gateway.do"


def _alipay_params(method: str, biz_content: dict) -> dict[str, str]:
    params = {
        "app_id": settings.ALIPAY_APP_ID,
        "method": method,
        "format": "JSON",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "biz_content": json.dumps(
            biz_content,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    canonical = "&".join(f"{key}={params[key]}" for key in sorted(params))
    if settings.ALIPAY_APP_CERT_PATH or settings.ALIPAY_ROOT_CERT_PATH:
        params.update(_alipay_certificate_params())
        canonical = "&".join(f"{key}={params[key]}" for key in sorted(params))
    params["sign"] = _rsa_sign(settings.ALIPAY_PRIVATE_KEY_PATH, canonical)
    return params


def _alipay_certificate_sn(cert: x509.Certificate) -> str:
    # Alipay uses MD5(issuer RFC2253 + decimal serial) as an identifier, not a security hash.
    content = cert.issuer.rfc4514_string() + str(cert.serial_number)
    return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()


def _alipay_certificate_params() -> dict[str, str]:
    try:
        if not settings.ALIPAY_APP_CERT_PATH or not settings.ALIPAY_ROOT_CERT_PATH:
            raise ValueError("missing certificate")
        app_cert = x509.load_pem_x509_certificate(Path(settings.ALIPAY_APP_CERT_PATH).read_bytes())
        platform_cert = x509.load_pem_x509_certificate(Path(settings.ALIPAY_PUBLIC_KEY_PATH).read_bytes())
        roots = x509.load_pem_x509_certificates(Path(settings.ALIPAY_ROOT_CERT_PATH).read_bytes())
        now = datetime.now(UTC)
        for cert in (app_cert, platform_cert):
            if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
                raise ValueError("certificate expired or not active")
        encoding, form = serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        if app_cert.public_key().public_bytes(encoding, form) != _private_key(settings.ALIPAY_PRIVATE_KEY_PATH).public_key().public_bytes(encoding, form):
            raise ValueError("application certificate does not match private key")
        root_sn = "_".join(_alipay_certificate_sn(cert) for cert in roots if cert.signature_algorithm_oid.dotted_string.startswith("1.2.840.113549.1.1."))
        if not root_sn:
            raise ValueError("missing RSA root certificate")
        return {"app_cert_sn": _alipay_certificate_sn(app_cert), "alipay_root_cert_sn": root_sn}
    except (OSError, ValueError, TypeError) as exc:
        raise CustomException(msg="支付宝证书配置不完整、已失效或与应用私钥不匹配", status_code=409) from exc


def _raw_json_field(payload: str, field: str) -> tuple[dict, str]:
    marker = f'"{field}"'
    marker_index = payload.find(marker)
    if marker_index < 0:
        raise CustomException(msg="支付宝查单响应格式无效", status_code=502)
    colon_index = payload.find(":", marker_index + len(marker))
    if colon_index < 0:
        raise CustomException(msg="支付宝查单响应格式无效", status_code=502)
    tail = payload[colon_index + 1 :]
    leading = len(tail) - len(tail.lstrip())
    try:
        value, length = json.JSONDecoder().raw_decode(tail.lstrip())
    except json.JSONDecodeError as exc:
        raise CustomException(msg="支付宝查单响应格式无效", status_code=502) from exc
    if not isinstance(value, dict):
        raise CustomException(msg="支付宝查单响应格式无效", status_code=502)
    return value, tail[leading : leading + length]


async def create_wechat_native_order(order_no: str, amount_fen: int, description: str) -> str:
    body = json.dumps(
        {
            "appid": settings.WECHAT_PAY_APP_ID,
            "mchid": settings.WECHAT_PAY_MCH_ID,
            "description": description[:127],
            "out_trade_no": order_no,
            "notify_url": f"{settings.PAYMENT_PUBLIC_BASE_URL.rstrip('/')}/payment/callback/wechat",
            "amount": {"total": amount_fen, "currency": "CNY"},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    path = "/v3/pay/transactions/native"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"https://api.mch.weixin.qq.com{path}",
            content=body.encode(),
            headers=_wechat_request_headers("POST", path, body, json_body=True),
        )
    if response.status_code >= 400:
        raise CustomException(msg=f"微信支付下单失败（HTTP {response.status_code}）", status_code=502)
    _verify_wechat_signed_message(
        {key.lower(): value for key, value in response.headers.items()},
        response.content,
    )
    code_url = response.json().get("code_url")
    if not code_url:
        raise CustomException(msg="微信支付未返回收款码", status_code=502)
    return str(code_url)


async def create_alipay_qr_order(
    order_no: str,
    amount_fen: int,
    subject: str,
    *,
    sandbox: bool = False,
) -> str:
    """Return the provider-issued order QR payload, never a page-pay gateway URL."""
    params = _alipay_params(
        "alipay.trade.precreate",
        {
            "out_trade_no": order_no,
            "total_amount": f"{Decimal(amount_fen) / 100:.2f}",
            "subject": subject[:256],
            "timeout_express": "15m",
            "qr_code_timeout_express": f"{ALIPAY_QR_TIMEOUT_MINUTES}m",
        },
    )
    params["notify_url"] = f"{settings.PAYMENT_PUBLIC_BASE_URL.rstrip('/')}/payment/callback/alipay"
    params.pop("sign")
    canonical = "&".join(f"{key}={params[key]}" for key in sorted(params))
    params["sign"] = _rsa_sign(settings.ALIPAY_PRIVATE_KEY_PATH, canonical)
    query_params = {"charset": params.pop("charset")}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(_alipay_gateway(sandbox), params=query_params, data=params)
    if response.status_code >= 400:
        raise CustomException(msg=f"支付宝扫码下单失败（HTTP {response.status_code}）", status_code=502)
    data, signed_content = _raw_json_field(response.text, "alipay_trade_precreate_response")
    envelope = json.loads(response.text)
    _rsa_verify(settings.ALIPAY_PUBLIC_KEY_PATH, signed_content, str(envelope.get("sign") or ""))
    if data.get("code") != "10000":
        raise CustomException(msg="支付宝扫码下单失败，请检查当前应用的当面付权限及商户配置", status_code=502)
    if data.get("out_trade_no") != order_no:
        raise CustomException(msg="支付宝扫码下单返回订单号不匹配", status_code=502)
    qr_code = data.get("qr_code")
    if not isinstance(qr_code, str) or not qr_code.strip():
        raise CustomException(msg="支付宝未返回付款二维码，请重新下单", status_code=502)
    return qr_code


def create_alipay_page_order(
    order_no: str,
    amount_fen: int,
    subject: str,
    return_url: str | None,
    *,
    sandbox: bool = False,
) -> str:
    params = _alipay_params(
        "alipay.trade.page.pay",
        {
            "out_trade_no": order_no,
            "product_code": "FAST_INSTANT_TRADE_PAY",
            "total_amount": f"{amount_fen / 100:.2f}",
            "subject": subject[:256],
        },
    )
    params["notify_url"] = f"{settings.PAYMENT_PUBLIC_BASE_URL.rstrip('/')}/payment/callback/alipay"
    if return_url:
        params["return_url"] = return_url
    # notify_url/return_url participate in the Alipay request signature.
    params.pop("sign")
    canonical = "&".join(f"{key}={params[key]}" for key in sorted(params))
    params["sign"] = _rsa_sign(settings.ALIPAY_PRIVATE_KEY_PATH, canonical)
    return f"{_alipay_gateway(sandbox)}?{urlencode(params)}"


async def query_wechat_order(order_no: str, *, include_closed: bool = False) -> VerifiedPayment | VerifiedClosedOrder | None:
    request_target = f"/v3/pay/transactions/out-trade-no/{order_no}?mchid={settings.WECHAT_PAY_MCH_ID}"
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"https://api.mch.weixin.qq.com{request_target}",
            headers=_wechat_request_headers("GET", request_target),
        )
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise CustomException(msg=f"微信支付查单失败（HTTP {response.status_code}）", status_code=502)
    _verify_wechat_signed_message(
        {key.lower(): value for key, value in response.headers.items()},
        response.content,
    )
    data = response.json()
    if data.get("appid") != settings.WECHAT_PAY_APP_ID or data.get("mchid") != settings.WECHAT_PAY_MCH_ID or data.get("amount", {}).get("currency") != "CNY" or data.get("out_trade_no") != order_no:
        raise CustomException(msg="微信支付查单身份、币种或订单号无效", status_code=502)
    if include_closed and data.get("trade_state") == "CLOSED":
        return VerifiedClosedOrder(order_no, int(data["amount"]["total"]))
    if data.get("trade_state") != "SUCCESS":
        return None
    transaction_id = str(data["transaction_id"])
    return VerifiedPayment(
        callback_id=f"query:{transaction_id}",
        order_no=order_no,
        provider_trade_no=transaction_id,
        amount_fen=int(data["amount"]["total"]),
        paid_at=datetime.fromisoformat(data["success_time"]) if data.get("success_time") else None,
        payload_digest=hashlib.sha256(response.content).hexdigest(),
    )


async def query_alipay_order(order_no: str, *, sandbox: bool = False, include_closed: bool = False) -> VerifiedPayment | VerifiedClosedOrder | VerifiedAbsentOrder | None:
    params = _alipay_params("alipay.trade.query", {"out_trade_no": order_no})
    # Alipay selects the response/signature encoding from the URL query string.
    # Keeping charset only in the POST body makes it default to GBK.
    query_params = {"charset": params.pop("charset")}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(_alipay_gateway(sandbox), params=query_params, data=params)
    if response.status_code >= 400:
        raise CustomException(msg=f"支付宝查单失败（HTTP {response.status_code}）", status_code=502)
    raw = response.text
    data, signed_content = _raw_json_field(raw, "alipay_trade_query_response")
    envelope = response.json()
    _rsa_verify(settings.ALIPAY_PUBLIC_KEY_PATH, signed_content, str(envelope.get("sign") or ""))
    if data.get("code") != "10000":
        if data.get("sub_code") == "ACQ.TRADE_NOT_EXIST":
            return VerifiedAbsentOrder(order_no) if include_closed else None
        raise CustomException(msg="支付宝查单返回业务错误", status_code=502)
    if data.get("out_trade_no") != order_no or (data.get("seller_user_id") and data.get("seller_user_id") != settings.ALIPAY_SELLER_ID):
        raise CustomException(msg="支付宝查单商户或订单号无效", status_code=502)
    if include_closed and data.get("trade_status") == "TRADE_CLOSED":
        return VerifiedClosedOrder(order_no, _amount_fen(str(data.get("total_amount") or ""), "支付宝查单"), previously_paid=bool(data.get("send_pay_date")))
    if data.get("trade_status") not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        return None
    trade_no = str(data["trade_no"])
    paid_at = datetime.strptime(data["send_pay_date"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(UTC) if data.get("send_pay_date") else None
    return VerifiedPayment(
        callback_id=f"query:{trade_no}",
        order_no=order_no,
        provider_trade_no=trade_no,
        amount_fen=_amount_fen(str(data.get("total_amount") or ""), "支付宝查单"),
        paid_at=paid_at,
        payload_digest=hashlib.sha256(response.content).hexdigest(),
    )


async def close_wechat_order(order_no: str) -> None:
    path = f"/v3/pay/transactions/out-trade-no/{order_no}/close"
    body = json.dumps({"mchid": settings.WECHAT_PAY_MCH_ID}, separators=(",", ":"))
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"https://api.mch.weixin.qq.com{path}", content=body.encode(), headers=_wechat_request_headers("POST", path, body, json_body=True))
    if response.status_code != 204:
        # ORDERPAID/ORDERNOTEXIST and transport errors are not proof of closure.
        raise CustomException(msg=f"微信支付关单未确认（HTTP {response.status_code}）", status_code=502)
    _verify_wechat_signed_message({key.lower(): value for key, value in response.headers.items()}, response.content)


async def close_alipay_order(order_no: str, *, sandbox: bool = False) -> None:
    params = _alipay_params("alipay.trade.close", {"out_trade_no": order_no})
    query_params = {"charset": params.pop("charset")}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(_alipay_gateway(sandbox), params=query_params, data=params)
    if response.status_code >= 400:
        raise CustomException(msg=f"支付宝关单未确认（HTTP {response.status_code}）", status_code=502)
    data, signed_content = _raw_json_field(response.text, "alipay_trade_close_response")
    _rsa_verify(settings.ALIPAY_PUBLIC_KEY_PATH, signed_content, str(response.json().get("sign") or ""))
    if data.get("code") != "10000" or data.get("out_trade_no") != order_no:
        # TRADE_STATUS_ERROR can mean paid or closed; only a signed query settles it.
        raise CustomException(msg="支付宝关单结果待核对，请查询原订单", status_code=502)


def verify_wechat_callback(headers: dict[str, str], raw_body: bytes) -> VerifiedPayment:
    _verify_wechat_signed_message(headers, raw_body)
    envelope = json.loads(raw_body)
    resource = envelope["resource"]
    plaintext = AESGCM(settings.WECHAT_PAY_API_V3_KEY.encode()).decrypt(
        str(resource["nonce"]).encode(),
        base64.b64decode(resource["ciphertext"]),
        str(resource.get("associated_data") or "").encode(),
    )
    data = json.loads(plaintext)
    if data.get("trade_state") != "SUCCESS" or data.get("appid") != settings.WECHAT_PAY_APP_ID or data.get("mchid") != settings.WECHAT_PAY_MCH_ID or data.get("amount", {}).get("currency") != "CNY":
        raise CustomException(msg="微信支付回调身份、币种或交易状态无效", status_code=400)
    paid_at = datetime.fromisoformat(data["success_time"]) if data.get("success_time") else None
    return VerifiedPayment(
        callback_id=str(envelope.get("id") or data["transaction_id"]),
        order_no=str(data["out_trade_no"]),
        provider_trade_no=str(data["transaction_id"]),
        amount_fen=int(data["amount"]["total"]),
        paid_at=paid_at,
        payload_digest=hashlib.sha256(raw_body).hexdigest(),
    )


def verify_alipay_callback(data: dict[str, str]) -> VerifiedPayment:
    signature = data.get("sign", "")
    canonical = "&".join(f"{key}={value}" for key, value in sorted(data.items()) if key not in {"sign", "sign_type"})
    _rsa_verify(settings.ALIPAY_PUBLIC_KEY_PATH, canonical, signature)
    if data.get("app_id") != settings.ALIPAY_APP_ID or data.get("seller_id") != settings.ALIPAY_SELLER_ID or data.get("trade_status") not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        raise CustomException(msg="支付宝回调状态无效", status_code=400)
    try:
        amount_fen = _amount_fen(data["total_amount"], "支付宝回调")
    except KeyError as exc:
        raise CustomException(msg="支付宝回调金额无效", status_code=400) from exc
    paid_at = datetime.strptime(data["gmt_payment"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(UTC) if data.get("gmt_payment") else None
    callback_id = data.get("notify_id") or hashlib.sha256(canonical.encode()).hexdigest()
    return VerifiedPayment(
        callback_id=callback_id,
        order_no=data["out_trade_no"],
        provider_trade_no=data["trade_no"],
        amount_fen=amount_fen,
        paid_at=paid_at,
        payload_digest=hashlib.sha256(canonical.encode()).hexdigest(),
    )
