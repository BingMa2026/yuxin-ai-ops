from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from auth_helpers import register_with_sms
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.module_growth.defaults import default_drafts
from app.api.v1.module_growth.engine import calculate_reward, evaluate, period_key
from app.api.v1.module_growth.schema import GradePolicy, RewardAction


def test_grade_scoring_missing_samples_and_configurable_windows():
    usage = default_drafts()[0].config
    result = evaluate(usage, {"net_paid_fen": 300000, "active_days": 30, "artifacts": 10, "feedback": 5})
    assert result["grade"] == "R3"
    assert result["score"] == 100
    assert evaluate(usage, {"net_paid_fen": 999999999})["grade"] == "R1"
    promotion = default_drafts()[1].config
    result = evaluate(promotion, {"registrations": 60, "first_users": 40, "first_payers": 24, "conversion_rate": 40, "retention_rate": None, "compliance_rate": 100, "refund_rate": 0})
    assert result["grade"] == "A1"
    assert result["insufficient"]
    changed = GradePolicy.model_validate({**promotion.model_dump(), "window_days": 30})
    assert changed.window_days == 30
    assert period_key(changed, datetime(2026, 8, 31, 16, tzinfo=UTC)) == "2026-09"


def test_reward_assets_are_not_gated_by_partner_identity():
    action = RewardAction(recipient="inviter", asset="cash", calculation="paid_percent", percent=Decimal(3), grade_percent={"A3": Decimal(10)})
    assert calculate_reward(action, net_paid_fen=10000, usage_grade="R1", promotion_grade="ungraded") == 300
    assert calculate_reward(action, net_paid_fen=10000, usage_grade="R1", promotion_grade="A3") == 1000
    assert calculate_reward(action, net_paid_fen=0, usage_grade="R3", promotion_grade="A3") == 0
    with pytest.raises(ValidationError):
        RewardAction(recipient="actor", asset="cash", amount=10, grade_percent={"A3": Decimal("NaN")})


def _new_client(test_client, app_code, invite_code=None):
    username = "growth_" + uuid4().hex[:12]
    body = {"app_code": app_code, "username": username, "password": "TestPass123!"}
    if invite_code:
        body["invite_code"] = invite_code
    registered = register_with_sms(test_client, body)
    assert registered.status_code == 200, registered.text
    login = test_client.post("/client/auth/login", json={k: v for k, v in body.items() if k != "invite_code"})
    assert login.status_code == 200, login.text
    return registered.json()["data"], {"Authorization": "Bearer " + login.json()["data"]["access_token"]}


def test_referral_registration_binding_and_unpublished_rule_loop(test_client: TestClient):
    login = test_client.post("/system/auth/login", data={"username": "admin", "password": "admin123"})
    staff = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
    app = test_client.get("/system/user/current/info", headers=staff).json()["data"]["current_app"]
    inviter, first = _new_client(test_client, app["code"])
    profile = test_client.get("/client/growth/me", headers=first)
    assert profile.status_code == 200, profile.text
    code = profile.json()["data"]["invite_code"]
    public = test_client.get(f"/public/growth/invitations/{code}")
    assert public.status_code == 200, public.text
    assert public.json()["data"]["app_code"] == app["code"]
    invitee, second = _new_client(test_client, app["code"], code)
    summary = test_client.get("/client/growth/me", headers=second).json()["data"]
    assert summary["binding"]["inviter_id"] == inviter["id"]
    assert summary["cash"]["available"] == 0
    assert not summary["binding"]["eligible"]
    assert test_client.post("/client/growth/bind", headers=second, json={"code": code}).status_code == 409
    assert test_client.post("/client/growth/bind", headers=first, json={"code": code}).status_code == 422
    records = test_client.get("/client/growth/referrals", headers=first).json()["data"]
    assert records["total"] == 1
    assert records["items"][0]["user_id"] is None
    seeded = test_client.post("/growth/rules/defaults", headers=staff)
    assert seeded.status_code == 200, seeded.text
    assert len(seeded.json()["data"]) >= 13
    assert all(r["status"] == "draft" for r in seeded.json()["data"])
    forbidden = test_client.get("/growth/rules", headers=second)
    assert forbidden.status_code in {401, 403}
    policies = seeded.json()["data"]
    rule = next(r for r in policies if r["kind"] == "incentive")
    published = test_client.post(f"/growth/rules/{rule['id']}/publish", headers=staff, json={"effective_at": datetime.now(UTC).isoformat()})
    assert published.status_code == 422


def test_save_and_publish_is_atomic_and_keeps_previous_version(test_client, auth_headers):
    rights = default_drafts()[2].model_dump(mode="json")
    published = test_client.post("/growth/rules/save-and-publish", headers=auth_headers, json=rights)
    assert published.status_code == 200, published.text
    assert published.json()["data"]["status"] == "published"
    incentive = default_drafts()[3].model_dump(mode="json")
    incentive["key"] = "atomic_" + uuid4().hex[:12]
    result = test_client.post("/growth/rules/save-and-publish", headers=auth_headers, json=incentive)
    assert result.status_code == 422
    rows = test_client.get("/growth/rules", headers=auth_headers).json()["data"]
    assert not any(r["key"] == incentive["key"] for r in rows)
    incentive["config"]["budget_credits"] = 100000
    success = test_client.post("/growth/rules/save-and-publish", headers=auth_headers, json=incentive)
    assert success.status_code == 200, success.text
    first = success.json()["data"]
    assert first["status"] == "published" and first["version"] == 1
    incentive["config"]["budget_credits"] = 0
    assert test_client.post("/growth/rules/save-and-publish", headers=auth_headers, json=incentive).status_code == 422
    rows = test_client.get("/growth/rules", headers=auth_headers).json()["data"]
    versions = [r for r in rows if r["key"] == incentive["key"]]
    assert len(versions) == 1 and versions[0]["id"] == first["id"]
    assert test_client.post("/growth/rules/save-and-publish", json=rights).status_code == 401
