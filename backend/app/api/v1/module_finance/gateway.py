"""Authenticated provider I/O. Unknown responses never imply money was returned."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from urllib.parse import quote

import httpx

from app.api.v1.module_payment.order.providers import _alipay_gateway, _alipay_params, _amount_fen, _raw_json_field, _rsa_verify, _verify_wechat_signed_message, _wechat_request_headers
from app.config.setting import settings
from app.core.exceptions import CustomException

from .common import BUSINESS_TZ


def identity(provider: str) -> str:
    return settings.ALIPAY_APP_ID if provider == "alipay" else settings.WECHAT_PAY_MCH_ID


async def alipay_request(method: str, body: dict) -> dict:
    params = _alipay_params(method, body)
    charset = params.pop("charset")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(_alipay_gateway(False), params={"charset": charset}, data=params)
    data, signed = _raw_json_field(response.text, method.replace(".", "_") + "_response")
    _rsa_verify(settings.ALIPAY_PUBLIC_KEY_PATH, signed, str(response.json().get("sign") or ""))
    if response.status_code != 200:
        raise CustomException(msg="支付宝请求未完成，请查单确认", status_code=502)
    return data


async def wechat_request(method: str, target: str, body: dict | None = None):
    content = json.dumps(body, ensure_ascii=False, separators=(",", ":")) if body is not None else ""
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.request(
            method,
            "https://api.mch.weixin.qq.com" + target,
            content=content.encode() if content else None,
            headers=_wechat_request_headers(method, target, content, json_body=body is not None),
        )
    _verify_wechat_signed_message(dict(response.headers), response.content)
    return response.status_code, response.json()


@dataclass(frozen=True)
class RefundResult:
    status: str
    provider_no: str = ""
    completed_at: datetime | None = None
    code: str = ""
    reason: str = ""


async def refund_request(provider: str, order_no: str, trade_no: str, refund_no: str, amount: int, total: int, reason: str, *, query: bool) -> RefundResult:
    if provider == "alipay":
        method = "alipay.trade.fastpay.refund.query" if query else "alipay.trade.refund"
        biz = {"out_trade_no": order_no, "out_request_no": refund_no}
        if query:
            biz["query_options"] = ["gmt_refund_pay"]
        else:
            biz.update(refund_amount=f"{Decimal(amount) / 100:.2f}", refund_reason=reason[:256])
        data = await alipay_request(method, biz)
        if data.get("code") != "10000":
            code = str(data.get("sub_code") or data.get("code"))
            rejected = {"ACQ.INVALID_PARAMETER", "ACQ.SELLER_BALANCE_NOT_ENOUGH", "ACQ.REFUND_AMT_NOT_EQUAL_TOTAL", "ACQ.REASON_TRADE_REFUND_FEE_ERR", "ACQ.TRADE_NOT_ALLOW_REFUND"}
            if not query and code in rejected:
                return RefundResult("failed", code=code, reason="渠道明确拒绝本次退款申请，请按返回码修正后重新申请")
            return RefundResult("unknown", code=str(data.get("sub_code") or data.get("code")), reason="渠道尚未确认退款结果，继续按原退款号核验")
        if data.get("out_trade_no") != order_no or data.get("trade_no") != trade_no:
            raise CustomException(msg="支付宝退款返回订单不匹配", status_code=502)
        # Submit responses are not enough to settle the ledger. Query the exact refund request.
        if not query:
            return RefundResult("processing")
        if data.get("out_request_no") != refund_no or _amount_fen(str(data.get("refund_amount", "")), "支付宝退款") != amount or _amount_fen(str(data.get("total_amount", "")), "支付宝退款") != total:
            raise CustomException(msg="支付宝退款查单金额或退款号不匹配", status_code=502)
        if data.get("refund_status") != "REFUND_SUCCESS":
            return RefundResult("processing")
        at = datetime.strptime(data["gmt_refund_pay"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=BUSINESS_TZ)
        return RefundResult("succeeded", hashlib.sha256(f"{order_no}:{refund_no}".encode()).hexdigest(), at)
    target = "/v3/refund/domestic/refunds" + ("/" + quote(refund_no, safe="") if query else "")
    body = None if query else {"out_trade_no": order_no, "out_refund_no": refund_no, "reason": reason[:80], "amount": {"refund": amount, "total": total, "currency": "CNY"}}
    status, data = await wechat_request("GET" if query else "POST", target, body)
    if status not in (200, 201):
        if not query and status in (400, 403) and data.get("code") in {"PARAM_ERROR", "NOT_ENOUGH", "INVALID_REQUEST"}:
            return RefundResult("failed", code=str(data["code"]), reason="渠道明确拒绝本次退款申请，请按返回码修正后重新申请")
        return RefundResult("unknown", code=str(data.get("code", "")), reason="渠道尚未确认退款结果，继续按原退款号核验")
    if (
        data.get("out_trade_no") != order_no
        or data.get("transaction_id") != trade_no
        or data.get("out_refund_no") != refund_no
        or data.get("amount", {}).get("refund") != amount
        or data.get("amount", {}).get("total") != total
        or data.get("amount", {}).get("currency") != "CNY"
    ):
        raise CustomException(msg="微信退款订单、退款号或金额不匹配", status_code=502)
    state = data.get("status")
    if state == "SUCCESS":
        return RefundResult("succeeded", str(data["refund_id"]), datetime.fromisoformat(data["success_time"]))
    if state == "CLOSED":
        return RefundResult("failed", str(data["refund_id"]), code="CLOSED", reason="渠道确认退款关闭，未完成退款")
    return RefundResult(
        "processing" if state == "PROCESSING" else "unknown", str(data.get("refund_id", "")), code=str(state or ""), reason="" if state == "PROCESSING" else "退款异常，请在商户平台核对并继续查单"
    )
