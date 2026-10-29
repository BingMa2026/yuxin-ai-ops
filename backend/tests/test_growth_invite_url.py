from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.module_growth.referral_service import ReferralService, parse_invite
from app.config.setting import settings
from app.core.exceptions import CustomException


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_official_invite_link_accepts_current_and_future_protocol(scheme):
    assert parse_invite(f"{scheme}://www.yxciedu.com/invite/ABCDEF123456") == "ABCDEF123456"


@pytest.mark.parametrize("url", ["ftp://www.yxciedu.com/invite/ABCDEF123456", "http://evil.example/invite/ABCDEF123456", "http://user@www.yxciedu.com/invite/ABCDEF123456"])
def test_invite_link_rejects_untrusted_urls(url):
    with pytest.raises(CustomException):
        parse_invite(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_summary_uses_configured_invite_url_and_persisted_code(monkeypatch, scheme):
    monkeypatch.setattr(settings, "GROWTH_INVITE_BASE_URL", f"{scheme}://www.yxciedu.com")
    db = AsyncMock()
    db.scalar.return_value = 0
    result = MagicMock()
    result.all.return_value = []
    db.execute.return_value = result
    service = ReferralService(db, 1)
    service.profile = AsyncMock(return_value=SimpleNamespace(invite_code="ABCDEF123456", usage_grade=1, promotion_grade=1, evaluations={}))
    service.eligibility = AsyncMock(return_value={"eligible": False})
    summary = await service.summary(1)
    assert summary["invite_url"] == f"{scheme}://www.yxciedu.com/invite/ABCDEF123456"
    assert summary["invite_code"] == "ABCDEF123456"
