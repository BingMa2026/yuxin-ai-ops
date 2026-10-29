"""Real merchant transfer adapters. Ambiguous responses never release frozen money."""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

from app.api.v1.module_payment.order.providers import (
    _alipay_certificate_params,
    _alipay_gateway,
    _alipay_params,
    _amount_fen,
    _raw_json_field,
    _rsa_verify,
    _verify_wechat_signed_message,
    _wechat_request_headers,
)
from app.config.setting import settings
from app.core.exceptions import CustomException


@dataclass(frozen=True)
class PayoutResult:
    state: str
    bill_no: str = ""
    package: str = ""
    reason: str = ""


def merchant_identity(provider: str) -> str:
    return f"{settings.WECHAT_PAY_MCH_ID}:{settings.GROWTH_WECHAT_APP_ID}" if provider == "wechat" else settings.ALIPAY_APP_ID


def _alipay_transfer_scene() -> dict:
    try:
        name = settings.GROWTH_ALIPAY_TRANSFER_SCENE_NAME.strip()
        reports = json.loads(settings.GROWTH_ALIPAY_SCENE_REPORT_JSON)
        if not name or not isinstance(reports, list) or not 1 <= len(reports) <= 5:
            raise ValueError("missing scene")
        if any(not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ("info_type", "info_content")) for item in reports):
            raise ValueError("invalid scene report")
        return {"transfer_scene_name": name, "transfer_scene_report_infos": reports}
    except (ValueError, TypeError) as exc:
        raise CustomException(msg="支付宝提现转账场景及上报信息尚未配置", status_code=409) from exc


def capabilities() -> list[dict]:
    try:
        Fernet(settings.GROWTH_PAYOUT_ENCRYPTION_KEY.encode())
        encryption = True
    except (ValueError, TypeError):
        encryption = False
    ali_reason = ""
    if not settings.GROWTH_ALIPAY_PAYOUT_ENABLED:
        ali_reason = "尚未启用支付宝商户转账"
    elif not encryption:
        ali_reason = "提现账户加密密钥尚未配置"
    elif not settings.ALIPAY_APP_ID:
        ali_reason = "支付宝应用尚未配置"
    else:
        try:
            _alipay_certificate_params()
            _alipay_transfer_scene()
        except CustomException as exc:
            ali_reason = exc.msg
    wechat = (
        encryption
        and settings.GROWTH_WECHAT_PAYOUT_ENABLED
        and all(
            [
                settings.WECHAT_PAY_MCH_ID,
                settings.GROWTH_WECHAT_APP_ID,
                settings.GROWTH_WECHAT_APP_SECRET,
                settings.WECHAT_PAY_MERCHANT_SERIAL_NO,
                settings.GROWTH_WECHAT_TRANSFER_SCENE_ID,
                settings.GROWTH_WECHAT_SCENE_REPORT_JSON,
            ]
        )
        and all(Path(p).is_file() for p in [settings.WECHAT_PAY_PRIVATE_KEY_PATH, settings.WECHAT_PAY_PUBLIC_KEY_PATH or settings.WECHAT_PAY_PLATFORM_CERT_PATH] if p)
        and bool(settings.WECHAT_PAY_PRIVATE_KEY_PATH and (settings.WECHAT_PAY_PUBLIC_KEY_PATH or settings.WECHAT_PAY_PLATFORM_CERT_PATH))
    )
    return [
        {"provider": "alipay", "available": not ali_reason, "reason": ali_reason},
        {"provider": "wechat", "available": bool(wechat), "reason": "" if wechat else "商户转账能力尚未开通或配置未完成"},
    ]


async def transfer(provider: str, out_bill_no: str, amount: int, payee: dict, *, query: bool = False) -> PayoutResult:
    if not query and not next(c["available"] for c in capabilities() if c["provider"] == provider):
        raise CustomException(msg="转账渠道尚未就绪", status_code=409)
    if provider == "alipay":
        method = "alipay.fund.trans.common.query" if query else "alipay.fund.trans.uni.transfer"
        body = {"out_biz_no": out_bill_no, "product_code": "TRANS_ACCOUNT_NO_PWD", "biz_scene": "DIRECT_TRANSFER"}
        if not query:
            body.update(
                {
                    "trans_amount": f"{Decimal(amount) / 100:.2f}",
                    "order_title": "推广奖励提现",
                    "remark": "推广奖励提现",
                    "payee_info": {"identity": payee["account"], "identity_type": "ALIPAY_LOGON_ID", "name": payee["name"]},
                }
            )
            body.update(_alipay_transfer_scene())
        params = _alipay_params(method, body)
        query_params = {"charset": params.pop("charset")}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(_alipay_gateway(False), params=query_params, data=params)
        data, signed = _raw_json_field(response.text, method.replace(".", "_") + "_response")
        _rsa_verify(settings.ALIPAY_PUBLIC_KEY_PATH, signed, str(response.json().get("sign") or ""))
        if response.status_code != 200 or data.get("code") != "10000":
            return PayoutResult("unknown", reason="渠道未确认结果，继续按原商户单号查单")
        if data.get("out_biz_no") != out_bill_no:
            raise CustomException(msg="转账查单编号不匹配", status_code=502)
        if query and _amount_fen(str(data.get("trans_amount", "")), "支付宝转账") != amount:
            raise CustomException(msg="转账查单金额不匹配", status_code=502)
        state = str(data.get("status", ""))
        return PayoutResult(
            {"SUCCESS": "succeeded", "FAIL": "failed", "DEALING": "processing"}.get(state, "unknown"), str(data.get("order_id") or ""), reason="渠道确认失败" if state == "FAIL" else ""
        )
    target = "/v3/fund-app/mch-transfer/transfer-bills" + (f"/out-bill-no/{out_bill_no}" if query else "")
    method = "GET" if query else "POST"
    body = (
        ""
        if query
        else json.dumps(
            {
                "appid": settings.GROWTH_WECHAT_APP_ID,
                "out_bill_no": out_bill_no,
                "transfer_scene_id": settings.GROWTH_WECHAT_TRANSFER_SCENE_ID,
                "openid": payee["openid"],
                "transfer_amount": amount,
                "transfer_remark": "推广奖励提现",
                "notify_url": f"{settings.PAYMENT_PUBLIC_BASE_URL.rstrip('/')}/public/growth/payout/wechat/callback",
                "transfer_scene_report_infos": json.loads(settings.GROWTH_WECHAT_SCENE_REPORT_JSON),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.request(
            method,
            f"https://api.mch.weixin.qq.com{target}",
            content=body or None,
            headers=_wechat_request_headers(method, target, body, json_body=True),
        )
    _verify_wechat_signed_message({k.lower(): v for k, v in response.headers.items()}, response.content)
    data = response.json()
    if response.status_code not in {200, 201}:
        return PayoutResult("unknown", reason="渠道未确认结果，继续按原商户单号查单")
    if data.get("out_bill_no") != out_bill_no or (query and (data.get("transfer_amount") != amount or data.get("openid") != payee["openid"] or data.get("appid") != settings.GROWTH_WECHAT_APP_ID)):
        raise CustomException(msg="微信转账订单校验失败", status_code=502)
    state = str(data.get("state") or "")
    return PayoutResult(
        {"SUCCESS": "succeeded", "FAIL": "failed", "CANCELLED": "failed", "WAIT_USER_CONFIRM": "confirming", "ACCEPTED": "processing", "PROCESSING": "processing", "TRANSFERING": "processing"}.get(
            state, "unknown"
        ),
        str(data.get("transfer_bill_no") or ""),
        str(data.get("package_info") or ""),
        "渠道确认失败或已撤销" if state in {"FAIL", "CANCELLED"} else "",
    )
