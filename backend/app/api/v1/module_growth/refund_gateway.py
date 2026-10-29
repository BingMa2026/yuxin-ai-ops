"""Read verified merchant refunds; this module never initiates a refund."""

import hashlib
from datetime import datetime
from urllib.parse import quote

import httpx
from sqlalchemy import func, select

from app.api.v1.module_payment.order.model import PaymentOrderModel, PaymentRefundModel
from app.api.v1.module_payment.order.providers import _alipay_gateway, _alipay_params, _amount_fen, _raw_json_field, _rsa_verify, _verify_wechat_signed_message, _wechat_request_headers
from app.config.setting import settings
from app.core.exceptions import CustomException

from .engine import BUSINESS_TZ
from .refund_service import reconcile_order_rewards
from .service import lock_app


async def query_refund(order: PaymentOrderModel, refund_no: str) -> dict:
    if order.provider == "wechat":
        target = "/v3/refund/domestic/refunds/" + quote(refund_no, safe="")
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get("https://api.mch.weixin.qq.com" + target, headers=_wechat_request_headers("GET", target))
        _verify_wechat_signed_message(dict(response.headers), response.content)
        data = response.json()
        amount = data.get("amount", {})
        valid = (
            response.status_code == 200
            and data.get("out_trade_no") == order.order_no
            and data.get("out_refund_no") == refund_no
            and data.get("transaction_id") == order.provider_trade_no
            and data.get("status") == "SUCCESS"
            and amount.get("total") == order.amount_fen
            and amount.get("currency") == "CNY"
        )
        if not valid:
            raise CustomException(msg="渠道尚未确认该订单退款成功，未修改账务", status_code=409)
        return {"amount": int(amount["refund"]), "provider_no": data["refund_id"], "at": datetime.fromisoformat(data["success_time"])}
    if order.provider != "alipay":
        raise CustomException(msg="当前支付渠道不支持退款核验", status_code=422)
    method = "alipay.trade.fastpay.refund.query"
    params = _alipay_params(method, {"out_trade_no": order.order_no, "out_request_no": refund_no, "query_options": ["gmt_refund_pay"]})
    charset = params.pop("charset")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(_alipay_gateway(False), params={"charset": charset}, data=params)
    data, signed = _raw_json_field(response.text, "alipay_trade_fastpay_refund_query_response")
    _rsa_verify(settings.ALIPAY_PUBLIC_KEY_PATH, signed, str(response.json().get("sign") or ""))
    if (
        response.status_code != 200
        or data.get("code") != "10000"
        or data.get("refund_status") != "REFUND_SUCCESS"
        or data.get("out_trade_no") != order.order_no
        or data.get("out_request_no") != refund_no
        or data.get("trade_no") != order.provider_trade_no
        or _amount_fen(str(data.get("total_amount", "")), "支付宝退款") != order.amount_fen
    ):
        raise CustomException(msg="渠道尚未确认该订单退款成功，未修改账务", status_code=409)
    at = datetime.strptime(data["gmt_refund_pay"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=BUSINESS_TZ)
    provider_no = hashlib.sha256(f"{order.order_no}:{refund_no}".encode()).hexdigest()
    return {"amount": _amount_fen(str(data["refund_amount"]), "支付宝退款"), "provider_no": provider_no, "at": at}


async def synchronize_refund(db, app_id: int, order_no: str, refund_no: str) -> dict:
    order = await db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.order_no == order_no, PaymentOrderModel.paid_at.is_not(None)))
    if not order:
        raise CustomException(msg="当前客户端下未找到已支付订单", status_code=404)
    verified = await query_refund(order, refund_no)
    await lock_app(db, app_id)
    key = "GXRF" + hashlib.sha256(f"{order.provider}:{order.order_no}:{refund_no}".encode()).hexdigest()[:56]
    existing = await db.scalar(select(PaymentRefundModel).where(PaymentRefundModel.provider == order.provider, PaymentRefundModel.provider_refund_no == verified["provider_no"]))
    if existing and (existing.app_id != app_id or existing.order_id != order.id or existing.amount_fen != verified["amount"]):
        raise CustomException(msg="退款记录与历史核验不一致，请联系财务核查", status_code=409)
    if not existing:
        total = int(
            await db.scalar(
                select(func.coalesce(func.sum(PaymentRefundModel.amount_fen), 0)).where(
                    PaymentRefundModel.app_id == app_id, PaymentRefundModel.order_id == order.id, PaymentRefundModel.status == "succeeded"
                )
            )
            or 0
        )
        if not 0 < verified["amount"] <= order.amount_fen - total:
            raise CustomException(msg="退款金额超出订单未退款余额", status_code=409)
        existing = PaymentRefundModel(
            app_id=app_id,
            user_id=order.user_id,
            order_id=order.id,
            refund_no=key,
            provider=order.provider,
            provider_refund_no=verified["provider_no"],
            amount_fen=verified["amount"],
            status="succeeded",
            refunded_at=verified["at"],
            reason="商户渠道查单核验",
        )
        db.add(existing)
        await db.flush()
    await reconcile_order_rewards(db, app_id, order.id)
    return {"id": existing.id, "status": existing.status, "amount_fen": existing.amount_fen}
