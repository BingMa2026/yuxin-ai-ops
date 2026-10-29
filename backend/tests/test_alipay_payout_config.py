import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.x509.oid import NameOID

from app.api.v1.module_growth import payout_providers as payout
from app.api.v1.module_payment.order import providers
from app.config.setting import settings
from app.core.exceptions import CustomException


@pytest.fixture
def certificates(monkeypatch, tmp_path):
    app_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    platform_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"), x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])

    def cert(key, serial, expired=False):
        now = datetime.now(UTC)
        return (
            x509.CertificateBuilder()
            .subject_name(issuer)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(serial)
            .not_valid_before(now - timedelta(days=2))
            .not_valid_after(now + timedelta(days=-1 if expired else 30))
            .sign(key, hashes.SHA256())
        )

    app_cert, platform_cert = cert(app_key, 123), cert(platform_key, 456)
    ignored_root = cert(ec.generate_private_key(ec.SECP256R1()), 789)
    files = {
        "ALIPAY_PRIVATE_KEY_PATH": app_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        "ALIPAY_PUBLIC_KEY_PATH": platform_cert.public_bytes(serialization.Encoding.PEM),
        "ALIPAY_APP_CERT_PATH": app_cert.public_bytes(serialization.Encoding.PEM),
        "ALIPAY_ROOT_CERT_PATH": ignored_root.public_bytes(serialization.Encoding.PEM) + platform_cert.public_bytes(serialization.Encoding.PEM),
    }
    for name, content in files.items():
        path = tmp_path / name
        path.write_bytes(content)
        monkeypatch.setattr(settings, name, str(path))
    for name, value in {
        "ALIPAY_APP_ID": "test-app",
        "GROWTH_ALIPAY_PAYOUT_ENABLED": True,
        "GROWTH_PAYOUT_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "GROWTH_ALIPAY_TRANSFER_SCENE_NAME": "佣金报酬",
        "GROWTH_ALIPAY_SCENE_REPORT_JSON": '[{"info_type":"佣金报酬说明","info_content":"测试推广佣金"}]',
        "GROWTH_WECHAT_PAYOUT_ENABLED": False,
    }.items():
        monkeypatch.setattr(settings, name, value)
    return app_key, platform_key, cert


def test_certificate_metadata_is_signed_and_rsa_roots_selected(certificates):
    app_key, _, _ = certificates
    params = providers._alipay_params("alipay.fund.trans.common.query", {"out_biz_no": "test-order"})
    assert params["app_cert_sn"] == hashlib.md5(b"CN=Test CA,C=CN123", usedforsecurity=False).hexdigest()
    assert params["alipay_root_cert_sn"] == hashlib.md5(b"CN=Test CA,C=CN456", usedforsecurity=False).hexdigest()
    sign = params.pop("sign")
    canonical = "&".join(f"{key}={params[key]}" for key in sorted(params))
    app_key.public_key().verify(base64.b64decode(sign), canonical.encode(), padding.PKCS1v15(), hashes.SHA256())
    assert payout.capabilities()[0]["available"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("GROWTH_PAYOUT_ENCRYPTION_KEY", ""),
        ("GROWTH_ALIPAY_PAYOUT_ENABLED", False),
        ("ALIPAY_APP_CERT_PATH", ""),
        ("ALIPAY_ROOT_CERT_PATH", "missing-file"),
        ("GROWTH_ALIPAY_TRANSFER_SCENE_NAME", ""),
        ("GROWTH_ALIPAY_SCENE_REPORT_JSON", "{}"),
        ("GROWTH_ALIPAY_SCENE_REPORT_JSON", '[{"info_type":"佣金报酬说明"}]'),
    ],
)
def test_incomplete_payout_config_is_unavailable(certificates, monkeypatch, field, value):
    monkeypatch.setattr(settings, field, value)
    cap = payout.capabilities()[0]
    assert cap["available"] is False
    assert cap["reason"]


@pytest.mark.parametrize("mode", ["mismatch", "expired"])
def test_certificate_must_match_private_key_and_be_current(certificates, mode):
    from pathlib import Path

    app_key, platform_key, cert = certificates
    replacement = cert(platform_key if mode == "mismatch" else app_key, 999, expired=mode == "expired")
    Path(settings.ALIPAY_APP_CERT_PATH).write_bytes(replacement.public_bytes(serialization.Encoding.PEM))
    with pytest.raises(CustomException):
        providers._alipay_params("alipay.fund.trans.common.query", {})
    assert payout.capabilities()[0]["available"] is False


def test_existing_public_key_payments_do_not_require_certificates(certificates, monkeypatch):
    monkeypatch.setattr(settings, "ALIPAY_APP_CERT_PATH", "")
    monkeypatch.setattr(settings, "ALIPAY_ROOT_CERT_PATH", "")
    params = providers._alipay_params("alipay.trade.precreate", {})
    assert "app_cert_sn" not in params
    assert "alipay_root_cert_sn" not in params
    assert payout.capabilities()[0]["available"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("query,tampered", [(False, False), (True, False), (False, True)])
async def test_transfer_and_query_signatures_charset_and_scene(certificates, monkeypatch, query, tampered):
    app_key, platform_key, _ = certificates

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, *, params, data):
            assert params == {"charset": "utf-8"}
            assert "charset" not in data
            signed = {**data, **params}
            signature = signed.pop("sign")
            app_key.public_key().verify(base64.b64decode(signature), "&".join(f"{k}={signed[k]}" for k in sorted(signed)).encode(), padding.PKCS1v15(), hashes.SHA256())
            body = json.loads(data["biz_content"])
            assert body["out_biz_no"] == "test-order"
            if query:
                assert "transfer_scene_name" not in body
            else:
                assert body["trans_amount"] == "629.10"
                assert body["transfer_scene_name"] == "佣金报酬"
                assert body["transfer_scene_report_infos"][0]["info_content"] == "测试推广佣金"
            response = json.dumps({"code": "10000", "out_biz_no": "test-order", "order_id": "ali-order", "status": "SUCCESS", "trans_amount": "629.10"}, separators=(",", ":"))
            sign = base64.b64encode(platform_key.sign(response.encode(), padding.PKCS1v15(), hashes.SHA256())).decode()
            if tampered:
                response = response.replace("629.10", "1.00")
            name = data["method"].replace(".", "_") + "_response"
            return httpx.Response(200, text='{"' + name + '":' + response + ',"sign":"' + sign + '"}')

    monkeypatch.setattr(payout.httpx, "AsyncClient", lambda **kwargs: Client())
    if tampered:
        with pytest.raises(CustomException):
            await payout.transfer("alipay", "test-order", 62910, {"account": "test@example.com", "name": "测试"}, query=query)
    else:
        result = await payout.transfer("alipay", "test-order", 62910, {"account": "test@example.com", "name": "测试"}, query=query)
        assert result.state == "succeeded"
