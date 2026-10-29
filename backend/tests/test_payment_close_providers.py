"""Verify real channel signatures before accepting a close response."""

import base64
import json
import time

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.api.v1.module_payment.order import providers
from app.config.setting import settings
from app.core.exceptions import CustomException


@pytest.fixture
def signing_key(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = tmp_path / "payment-public.pem"
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    monkeypatch.setattr(settings, "ALIPAY_PUBLIC_KEY_PATH", str(public))
    monkeypatch.setattr(settings, "ALIPAY_SELLER_ID", "seller-test")
    monkeypatch.setattr(settings, "WECHAT_PAY_PUBLIC_KEY_PATH", str(public))
    monkeypatch.setattr(settings, "WECHAT_PAY_PUBLIC_KEY_ID", "PUB_KEY_ID_TEST")
    monkeypatch.setattr(settings, "WECHAT_PAY_APP_ID", "wx-test")
    monkeypatch.setattr(settings, "WECHAT_PAY_MCH_ID", "merchant-test")
    monkeypatch.setattr(providers, "_rsa_sign", lambda *_args: "request-signature")
    monkeypatch.setattr(providers, "_wechat_authorization", lambda *_args: "request-signature")
    return key


def wechat_response(key, status=204, payload=None, tampered=False):
    raw = json.dumps(payload).encode() if payload is not None else b""
    timestamp, nonce = str(int(time.time())), "response-nonce"
    signed = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + raw + b"\n"
    signature = base64.b64encode(key.sign(signed, padding.PKCS1v15(), hashes.SHA256())).decode()
    if tampered:
        signature = signature[:-4] + "AAAA"
    return httpx.Response(status, content=raw, headers={"Wechatpay-Timestamp": timestamp, "Wechatpay-Nonce": nonce, "Wechatpay-Serial": "PUB_KEY_ID_TEST", "Wechatpay-Signature": signature})


def alipay_response(key, method, data, tampered=False):
    raw = json.dumps(data, separators=(",", ":"))
    signature = base64.b64encode(key.sign(raw.encode(), padding.PKCS1v15(), hashes.SHA256())).decode()
    if tampered:
        raw = raw.replace("YXCLOSE001", "YXTAMPER001")
    return httpx.Response(200, text='{"' + method + '":' + raw + ',"sign":"' + signature + '"}')


def install_response(monkeypatch, response, calls):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return response

        async def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return response

    monkeypatch.setattr(providers.httpx, "AsyncClient", lambda **_kwargs: FakeClient())


@pytest.mark.parametrize("case", ["success", "tampered", "paid", "missing"])
async def test_wechat_close_requires_verified_204(signing_key, monkeypatch, case):
    status = 204 if case in {"success", "tampered"} else 400
    response = wechat_response(signing_key, status, None if status == 204 else {"code": "ORDERPAID" if case == "paid" else "ORDERNOTEXIST"}, tampered=case == "tampered")
    calls = []
    install_response(monkeypatch, response, calls)
    if case == "success":
        await providers.close_wechat_order("YXCLOSE001")
    else:
        with pytest.raises(CustomException):
            await providers.close_wechat_order("YXCLOSE001")
    assert calls[0][0].endswith("/v3/pay/transactions/out-trade-no/YXCLOSE001/close")
    assert json.loads(calls[0][1]["content"]) == {"mchid": "merchant-test"}


@pytest.mark.parametrize("case", ["success", "tampered", "wrong_order", "unknown", "missing"])
async def test_alipay_close_requires_signed_success_for_original_order(signing_key, monkeypatch, case):
    data = {"code": "10000", "out_trade_no": "OTHER" if case == "wrong_order" else "YXCLOSE001"}
    if case in {"unknown", "missing"}:
        data = {"code": "40004", "sub_code": "ACQ.TRADE_STATUS_ERROR" if case == "unknown" else "ACQ.TRADE_NOT_EXIST"}
    calls = []
    install_response(monkeypatch, alipay_response(signing_key, "alipay_trade_close_response", data, case == "tampered"), calls)
    if case == "success":
        await providers.close_alipay_order("YXCLOSE001", sandbox=True)
    else:
        with pytest.raises(CustomException):
            await providers.close_alipay_order("YXCLOSE001", sandbox=True)
    assert calls[0][1]["data"]["method"] == "alipay.trade.close"
    assert calls[0][1]["params"]["charset"] == "utf-8"


@pytest.mark.parametrize("provider", ["wechat", "alipay"])
async def test_signed_closed_queries_are_distinct_from_payments(signing_key, monkeypatch, provider):
    if provider == "wechat":
        response = wechat_response(
            signing_key, 200, {"appid": "wx-test", "mchid": "merchant-test", "out_trade_no": "YXCLOSE001", "trade_state": "CLOSED", "amount": {"total": 1200, "currency": "CNY"}}
        )
        query = providers.query_wechat_order
    else:
        response = alipay_response(
            signing_key, "alipay_trade_query_response", {"code": "10000", "out_trade_no": "YXCLOSE001", "seller_user_id": "seller-test", "trade_status": "TRADE_CLOSED", "total_amount": "12.00"}
        )
        query = providers.query_alipay_order
    install_response(monkeypatch, response, [])
    closed = await query("YXCLOSE001", include_closed=True)
    assert isinstance(closed, providers.VerifiedClosedOrder) and closed.amount_fen == 1200
    assert await query("YXCLOSE001") is None


async def test_paid_then_refunded_alipay_closure_requires_finance_review(signing_key, monkeypatch):
    response = alipay_response(
        signing_key,
        "alipay_trade_query_response",
        {"code": "10000", "out_trade_no": "YXCLOSE001", "seller_user_id": "seller-test", "trade_status": "TRADE_CLOSED", "total_amount": "12.00", "send_pay_date": "2026-10-14 12:00:00"},
    )
    install_response(monkeypatch, response, [])
    result = await providers.query_alipay_order("YXCLOSE001", include_closed=True)
    assert isinstance(result, providers.VerifiedClosedOrder) and result.previously_paid


@pytest.mark.parametrize("tampered", [False, True])
async def test_alipay_absence_is_typed_only_after_signature_verification(signing_key, monkeypatch, tampered):
    data = {"code": "40004", "sub_code": "ACQ.TRADE_NOT_EXIST", "out_trade_no": "YXCLOSE001"}
    install_response(monkeypatch, alipay_response(signing_key, "alipay_trade_query_response", data, tampered), [])
    if tampered:
        with pytest.raises(CustomException, match="签名校验失败"):
            await providers.query_alipay_order("YXCLOSE001", include_closed=True)
    else:
        result = await providers.query_alipay_order("YXCLOSE001", include_closed=True)
        assert isinstance(result, providers.VerifiedAbsentOrder) and result.order_no == "YXCLOSE001"
        assert await providers.query_alipay_order("YXCLOSE001") is None
