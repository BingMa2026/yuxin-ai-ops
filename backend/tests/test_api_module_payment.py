"""支付渠道接口安全边界与基础行为。"""

import base64
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from app.api.v1.module_payment.channel.service import PaymentChannelService
from app.api.v1.module_payment.order import providers
from app.config.setting import settings
from app.core.exceptions import CustomException


class TestPaymentChannel:
    @pytest.mark.parametrize("case", ["success", "tampered", "wrong_order", "missing_qr", "denied"])
    async def test_alipay_precreate_returns_verified_provider_qr(self, monkeypatch, tmp_path, case):
        app_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        platform_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_path, public_path = tmp_path / "app.pem", tmp_path / "platform.pem"
        private_path.write_bytes(app_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        public_path.write_bytes(platform_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        monkeypatch.setattr(settings, "ALIPAY_PRIVATE_KEY_PATH", str(private_path))
        monkeypatch.setattr(settings, "ALIPAY_PUBLIC_KEY_PATH", str(public_path))
        monkeypatch.setattr(settings, "PAYMENT_PUBLIC_BASE_URL", "https://merchant.example/api/v1")
        qr = "https://qr.alipay.com/provider-issued-order"

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, url, *, params, data):
                assert params == {"charset": "utf-8"}
                assert data["method"] == "alipay.trade.precreate"
                assert data["notify_url"] == "https://merchant.example/api/v1/payment/callback/alipay"
                biz = providers.json.loads(data["biz_content"])
                assert biz["total_amount"] == "629.10" and biz["subject"] == "企业积分包"
                assert biz["timeout_express"] == "15m"
                assert biz["qr_code_timeout_express"] == "15m"
                signed_params = {**data, **params}
                signature = signed_params.pop("sign")
                canonical = "&".join(f"{k}={signed_params[k]}" for k in sorted(signed_params))
                app_key.public_key().verify(base64.b64decode(signature), canonical.encode(), padding.PKCS1v15(), hashes.SHA256())
                node = {"code": "10000", "out_trade_no": "YXQR001", "qr_code": qr}
                if case == "wrong_order":
                    node["out_trade_no"] = "ANOTHER_ORDER"
                if case == "missing_qr":
                    node.pop("qr_code")
                if case == "denied":
                    node = {"code": "40004", "sub_code": "ACQ.ACCESS_FORBIDDEN"}
                raw = providers.json.dumps(node, separators=(",", ":"))
                signature = base64.b64encode(platform_key.sign(raw.encode(), padding.PKCS1v15(), hashes.SHA256())).decode()
                if case == "tampered":
                    raw = raw.replace(qr, "https://qr.alipay.com/tampered")
                return httpx.Response(200, text='{"alipay_trade_precreate_response":' + raw + ',"sign":"' + signature + '"}')

        monkeypatch.setattr(providers.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
        if case == "success":
            assert await providers.create_alipay_qr_order("YXQR001", 62910, "企业积分包") == qr
        else:
            with pytest.raises(CustomException):
                await providers.create_alipay_qr_order("YXQR001", 62910, "企业积分包")

    @pytest.mark.parametrize("valid_signature", [True, False])
    async def test_wechat_native_returns_provider_code_only_after_verification(self, monkeypatch, valid_signature):
        qr = "weixin://wxpay/bizpayurl?pr=provider-order"
        verified = []
        monkeypatch.setattr(settings, "WECHAT_PAY_PUBLIC_KEY_ID", "PUB_KEY_ID_TEST")
        monkeypatch.setattr(settings, "WECHAT_PAY_PUBLIC_KEY_PATH", "/tmp/wechat-public.pem")

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, url, **kwargs):
                assert url.endswith("/v3/pay/transactions/native")
                assert kwargs["headers"]["Wechatpay-Serial"] == "PUB_KEY_ID_TEST"
                return httpx.Response(200, json={"code_url": qr})

        def verify(*_args):
            if not valid_signature:
                raise CustomException(msg="支付回调签名校验失败", status_code=400)
            verified.append(True)

        monkeypatch.setattr(providers, "_wechat_authorization", lambda *_args: "signed")
        monkeypatch.setattr(providers, "_verify_wechat_signed_message", verify)
        monkeypatch.setattr(providers.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
        if valid_signature:
            assert await providers.create_wechat_native_order("YXQR002", 100, "订阅") == qr
            assert verified == [True]
        else:
            with pytest.raises(CustomException):
                await providers.create_wechat_native_order("YXQR002", 100, "订阅")

    def test_list_contains_only_supported_channels(self, test_client: TestClient, auth_headers: dict) -> None:
        response = test_client.get("/payment/channel/list", headers=auth_headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["code"] == 0
        channels = payload["data"]
        assert {item["provider"] for item in channels} == {"wechat", "alipay"}
        assert all("private_key" not in item and "api_v3_key" not in item for item in channels)

    def test_unconfigured_channel_cannot_be_enabled(self, test_client: TestClient, auth_headers: dict) -> None:
        response = test_client.put(
            "/payment/channel/toggle/wechat",
            headers=auth_headers,
            json={"enabled": True},
        )
        assert response.status_code == 400
        assert "环境配置未就绪" in response.json()["msg"]

    def test_channel_can_remain_disabled(self, test_client: TestClient, auth_headers: dict) -> None:
        response = test_client.put(
            "/payment/channel/toggle/alipay",
            headers=auth_headers,
            json={"enabled": False},
        )
        assert response.status_code == 200
        assert response.json()["data"]["enabled"] is False

    def test_wechat_public_key_can_replace_platform_certificate(self, monkeypatch, tmp_path: Path) -> None:
        merchant_private_key = tmp_path / "merchant-private.pem"
        wechat_public_key = tmp_path / "wechat-public.pem"
        merchant_private_key.write_text("merchant-private-key", encoding="utf-8")
        wechat_public_key.write_text("wechat-public-key", encoding="utf-8")

        values = {
            "WECHAT_PAY_APP_ID": "wx-test-app",
            "WECHAT_PAY_MCH_ID": "1900000001",
            "WECHAT_PAY_MERCHANT_SERIAL_NO": "SERIAL-NO",
            "WECHAT_PAY_PRIVATE_KEY_PATH": str(merchant_private_key),
            "WECHAT_PAY_PLATFORM_CERT_PATH": "",
            "WECHAT_PAY_PUBLIC_KEY_ID": "PUB_KEY_ID_TEST",
            "WECHAT_PAY_PUBLIC_KEY_PATH": str(wechat_public_key),
            "WECHAT_PAY_API_V3_KEY": "1" * 32,
            "PAYMENT_PUBLIC_BASE_URL": "https://pay.example.com",
        }
        for field, value in values.items():
            monkeypatch.setattr(settings, field, value)

        service = PaymentChannelService(auth=None, db=None)  # type: ignore[arg-type]
        missing, identity, notify_configured = service._runtime_status("wechat")

        assert missing == []
        assert identity == "1900****0001"
        assert notify_configured is True

    def test_invalid_payment_public_url_is_not_ready(self, monkeypatch, tmp_path: Path) -> None:
        app_private_key = tmp_path / "alipay-app-private.pem"
        alipay_public_key = tmp_path / "alipay-public.pem"
        app_private_key.write_text("app-private-key", encoding="utf-8")
        alipay_public_key.write_text("alipay-public-key", encoding="utf-8")

        values = {
            "ALIPAY_APP_ID": "2021000000000000",
            "ALIPAY_SELLER_ID": "2088000000000000",
            "ALIPAY_PRIVATE_KEY_PATH": str(app_private_key),
            "ALIPAY_PUBLIC_KEY_PATH": str(alipay_public_key),
            "PAYMENT_PUBLIC_BASE_URL": "119.45.121.36",
        }
        for field, value in values.items():
            monkeypatch.setattr(settings, field, value)

        service = PaymentChannelService(auth=None, db=None)  # type: ignore[arg-type]
        missing, _, notify_configured = service._runtime_status("alipay")

        assert missing == ["PAYMENT_PUBLIC_BASE_URL"]
        assert notify_configured is False

    @pytest.mark.parametrize(
        "value",
        [
            "http://localhost:8001",
            "http://127.0.0.1:8001",
            "http://192.168.1.8",
            "https://user:password@pay.example.com",
            "https://payment.local",
            "http://[::1",
        ],
    )
    def test_private_or_credentialed_callback_url_is_rejected(self, value: str) -> None:
        assert PaymentChannelService._is_valid_http_url(value) is False

    def test_public_callback_url_is_accepted(self) -> None:
        assert PaymentChannelService._is_valid_http_url("https://pay.example.com") is True

    def test_production_callback_requires_https(self, monkeypatch, tmp_path: Path) -> None:
        app_private_key = tmp_path / "alipay-app-private.pem"
        alipay_public_key = tmp_path / "alipay-public.pem"
        app_private_key.write_text("app-private-key", encoding="utf-8")
        alipay_public_key.write_text("alipay-public-key", encoding="utf-8")

        values = {
            "ALIPAY_APP_ID": "2021000000000000",
            "ALIPAY_SELLER_ID": "2088000000000000",
            "ALIPAY_PRIVATE_KEY_PATH": str(app_private_key),
            "ALIPAY_PUBLIC_KEY_PATH": str(alipay_public_key),
            "PAYMENT_PUBLIC_BASE_URL": "http://pay.example.com",
        }
        for field, value in values.items():
            monkeypatch.setattr(settings, field, value)

        service = PaymentChannelService(auth=None, db=None)  # type: ignore[arg-type]
        production_missing, _, production_notify_ready = service._runtime_status("alipay", "production")
        sandbox_missing, _, sandbox_notify_ready = service._runtime_status("alipay", "sandbox")

        assert production_missing == ["PAYMENT_PUBLIC_BASE_URL"]
        assert production_notify_ready is False
        assert sandbox_missing == []
        assert sandbox_notify_ready is True

    def test_wechat_callback_public_key_id_must_match(self, monkeypatch, tmp_path: Path) -> None:
        public_key = tmp_path / "wechat-public.pem"
        public_key.write_text("placeholder", encoding="utf-8")
        monkeypatch.setattr(settings, "WECHAT_PAY_PUBLIC_KEY_PATH", str(public_key))
        monkeypatch.setattr(settings, "WECHAT_PAY_PUBLIC_KEY_ID", "PUB_KEY_ID_EXPECTED")

        with pytest.raises(CustomException, match="公钥ID不匹配"):
            providers._wechat_verify_path("PUB_KEY_ID_OTHER")

    def test_wechat_platform_certificate_remains_available_during_public_key_switch(self, monkeypatch, tmp_path: Path) -> None:
        from types import SimpleNamespace

        public_key = tmp_path / "wechat-public.pem"
        certificate = tmp_path / "wechat-platform.pem"
        public_key.write_text("public key placeholder", encoding="utf-8")
        certificate.write_text("certificate placeholder", encoding="utf-8")
        monkeypatch.setattr(settings, "WECHAT_PAY_PUBLIC_KEY_ID", "PUB_KEY_ID_EXPECTED")
        monkeypatch.setattr(settings, "WECHAT_PAY_PUBLIC_KEY_PATH", str(public_key))
        monkeypatch.setattr(settings, "WECHAT_PAY_PLATFORM_CERT_PATH", str(certificate))
        monkeypatch.setattr(providers.x509, "load_pem_x509_certificate", lambda _raw: SimpleNamespace(serial_number=0x1234ABCD))

        assert providers._wechat_verify_path("PUB_KEY_ID_EXPECTED") == str(public_key)
        assert providers._wechat_verify_path("1234ABCD") == str(certificate)
        with pytest.raises(CustomException, match="序列号不匹配"):
            providers._wechat_verify_path("1234ABCE")

    def test_alipay_callback_checks_seller_and_decimal_amount(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ALIPAY_APP_ID", "2021000000000000")
        monkeypatch.setattr(settings, "ALIPAY_SELLER_ID", "2088000000000000")
        monkeypatch.setattr(providers, "_rsa_verify", lambda *_args: None)
        callback = {
            "sign": "signed",
            "app_id": "2021000000000000",
            "seller_id": "2088000000000000",
            "trade_status": "TRADE_SUCCESS",
            "notify_id": "notify-1",
            "out_trade_no": "OPS202609030001",
            "trade_no": "ALI202609030001",
            "total_amount": "12.34",
        }

        verified = providers.verify_alipay_callback(callback)
        assert verified.amount_fen == 1234

        callback["seller_id"] = "2088000000000001"
        with pytest.raises(CustomException, match="回调状态无效"):
            providers.verify_alipay_callback(callback)

    async def test_wechat_active_query_parses_verified_paid_order(self, monkeypatch) -> None:
        payload = {
            "appid": "wx-test-app",
            "mchid": "1900000001",
            "out_trade_no": "YXQUERY001",
            "transaction_id": "WXTRADE001",
            "trade_state": "SUCCESS",
            "success_time": "2026-09-03T12:00:00+08:00",
            "amount": {"total": 1234, "currency": "CNY"},
        }

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, *_args, **_kwargs):
                return httpx.Response(200, json=payload)

        monkeypatch.setattr(settings, "WECHAT_PAY_APP_ID", "wx-test-app")
        monkeypatch.setattr(settings, "WECHAT_PAY_MCH_ID", "1900000001")
        monkeypatch.setattr(providers, "_wechat_authorization", lambda *_args: "signed")
        monkeypatch.setattr(providers, "_verify_wechat_signed_message", lambda *_args: None)
        monkeypatch.setattr(providers.httpx, "AsyncClient", lambda **_kwargs: FakeClient())

        verified = await providers.query_wechat_order("YXQUERY001")

        assert verified is not None
        assert verified.amount_fen == 1234
        assert verified.provider_trade_no == "WXTRADE001"
        assert len(verified.payload_digest) == 64

    async def test_alipay_active_query_verifies_and_parses_paid_order(self, monkeypatch) -> None:
        response_node = {
            "code": "10000",
            "trade_status": "TRADE_SUCCESS",
            "out_trade_no": "YXQUERY002",
            "trade_no": "ALITRADE002",
            "seller_user_id": "2088000000000000",
            "total_amount": "12.34",
            "send_pay_date": "2026-09-03 12:00:00",
        }
        raw = '{"alipay_trade_query_response":' + providers.json.dumps(response_node, ensure_ascii=False, separators=(",", ":")) + ',"sign":"signed"}'

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **_kwargs):
                return httpx.Response(200, content=raw.encode())

        monkeypatch.setattr(settings, "ALIPAY_SELLER_ID", "2088000000000000")
        monkeypatch.setattr(providers, "_rsa_sign", lambda *_args: "signed")
        monkeypatch.setattr(providers, "_rsa_verify", lambda *_args: None)
        monkeypatch.setattr(providers.httpx, "AsyncClient", lambda **_kwargs: FakeClient())

        verified = await providers.query_alipay_order("YXQUERY002")

        assert verified is not None
        assert verified.amount_fen == 1234
        assert verified.provider_trade_no == "ALITRADE002"
        assert verified.paid_at is not None and verified.paid_at.utcoffset().total_seconds() == 0

    @pytest.mark.parametrize("tampered", [False, True])
    async def test_alipay_query_negotiates_utf8_and_checks_chinese_response_signature(self, monkeypatch, tmp_path, tampered) -> None:
        platform_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_path = tmp_path / "platform.pem"
        public_path.write_bytes(platform_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        signed_node = '{"code":"40004","sub_code":"ACQ.TRADE_NOT_EXIST","sub_msg":"交易不存在"}'

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, url, *, data, params=None):
                # The gateway chooses its response encoding from the URL, not the POST body.
                charset = (params or {}).get("charset", "gbk")
                signature = platform_key.sign(signed_node.encode(charset), padding.PKCS1v15(), hashes.SHA256())
                returned_node = signed_node.replace("交易不存在", "交易已修改") if tampered else signed_node
                envelope = '{"alipay_trade_query_response":' + returned_node + ',"sign":"' + base64.b64encode(signature).decode() + '"}'
                return httpx.Response(200, content=envelope.encode(charset), headers={"content-type": f"text/html;charset={charset}"})

        monkeypatch.setattr(settings, "ALIPAY_PUBLIC_KEY_PATH", str(public_path))
        monkeypatch.setattr(providers, "_rsa_sign", lambda *_args: "request-signature")
        monkeypatch.setattr(providers.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
        if tampered:
            with pytest.raises(CustomException, match="签名校验失败"):
                await providers.query_alipay_order("YXENCODING001")
        else:
            assert await providers.query_alipay_order("YXENCODING001") is None
