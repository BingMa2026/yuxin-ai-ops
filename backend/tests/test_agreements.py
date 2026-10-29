from uuid import uuid4

import pytest
from auth_helpers import register_with_sms

BASE = "/operations/agreements"


def data(response, status=200):
    assert response.status_code == status, response.text
    return response.json()["data"]


@pytest.fixture
def agreement_app(test_client):
    client = test_client
    token = data(client.post("/system/auth/login", data={"username": "admin", "password": "admin123"}))["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    original = data(client.get("/system/user/current/info", headers=headers))["current_app"]["id"]
    code = f"agreements_{uuid4().hex[:10]}"
    app = data(client.post("/operations/client-apps", headers=headers, json={"name": "协议测试客户端", "code": code, "status": "active", "registration_enabled": True}), 201)
    switched = data(client.post("/system/auth/select-app", headers=headers, json={"app_id": app["id"]}))
    headers = {"Authorization": f"Bearer {switched['access_token']}"}
    yield client, headers, app, original


def create(client, headers, code="user_agreement"):
    return data(
        client.post(
            BASE,
            headers=headers,
            json={
                "code": code,
                "title": "用户协议",
                "content": '<h2>使用规则</h2><p>正文 <strong>重点</strong><img src=x onerror=alert(1)><a href="javascript:alert(1)">链接</a></p>',
                "change_summary": "首次发布",
            },
        )
    )


def publish(client, headers, row):
    return data(client.post(f"{BASE}/{row['id']}/publish", headers=headers, json={"revision": row["revision"]}))


def test_draft_publication_history_and_conflict(agreement_app):
    client, headers, app, _ = agreement_app
    row = create(client, headers)
    public = f"/public/client-apps/{app['code']}/agreements/user_agreement"
    assert client.get(public).status_code == 404
    assert "onerror" not in row["content"] and "javascript:" not in row["content"]
    assert "<strong>重点</strong>" in row["content"]
    row = publish(client, headers, row)
    response = client.get(public)
    assert response.headers["cache-control"] == "no-store"
    first = data(response)
    assert first["version"] == 1
    payload = {"code": row["code"], "title": "新名称", "content": "<p>修订后的正文</p>", "change_summary": "修订内容", "revision": row["revision"]}
    draft = data(client.put(f"{BASE}/{row['id']}", headers=headers, json=payload))
    assert data(client.get(public)) == first
    assert client.put(f"{BASE}/{row['id']}", headers=headers, json=payload).status_code == 409
    assert client.post(f"{BASE}/{row['id']}/publish", headers=headers, json={"revision": row["revision"]}).status_code == 409
    row = publish(client, headers, draft)
    assert data(client.get(public))["title"] == "新名称"
    history = data(client.get(f"{BASE}/{row['id']}/versions", headers=headers))
    assert [v["version"] for v in history] == [2, 1]
    assert history[-1]["content"] == first["content"]
    restored = data(client.post(f"{BASE}/{row['id']}/versions/{history[-1]['id']}/restore", headers=headers, json={"revision": row["revision"]}))
    assert restored["content"] == first["content"] and restored["has_draft"]
    assert data(client.get(public))["version"] == 2
    assert publish(client, headers, restored)["current_version"] == 3


def test_scene_order_registration_acceptance_and_stale_version(agreement_app):
    client, headers, app, _ = agreement_app
    first = publish(client, headers, create(client, headers))
    second = publish(client, headers, create(client, headers, "privacy_policy"))
    scene = data(client.post(f"{BASE}/scenes", headers=headers, json={"code": "auth", "name": "登录注册", "agreement_ids": [second["id"], first["id"]]}))
    public_url = f"/public/client-apps/{app['code']}/agreement-scenes/auth"
    public = data(client.get(public_url))
    assert [a["code"] for a in public["agreements"]] == ["privacy_policy", "user_agreement"]
    credentials = {"app_code": app["code"], "username": "agreement_member", "password": "Passw0rd!", "mobile": "13800138000", "sms_code": "123456"}
    assert client.post("/client/auth/register", json=credentials).status_code == 409
    acceptance = {"scene_revision": public["revision"], "version_ids": [a["version_id"] for a in public["agreements"]]}
    updated = data(
        client.put(f"{BASE}/{first['id']}", headers=headers, json={"code": first["code"], "title": first["title"], "content": "<p>新版</p>", "change_summary": "更新", "revision": first["revision"]})
    )
    publish(client, headers, updated)
    assert client.post("/client/auth/register", json={**credentials, "agreement_acceptance": acceptance}).status_code == 409
    public = data(client.get(public_url))
    acceptance["version_ids"] = [a["version_id"] for a in public["agreements"]]
    user = data(register_with_sms(client, {**credentials, "agreement_acceptance": acceptance}))
    records = data(client.get(f"{BASE}/acceptances", headers=headers, params={"user_id": user["id"]}))
    assert records["total"] == 1
    assert records["items"][0]["version_ids"] == acceptance["version_ids"]
    assert records["items"][0]["business_ref"] == f"registration:{user['id']}"
    assert client.post(f"{BASE}/{second['id']}/archive", headers=headers, json={"revision": second["revision"]}).status_code == 409
    assert client.delete(f"{BASE}/scenes/{scene['id']}", headers=headers, params={"revision": scene["revision"]}).status_code == 400


def test_cross_client_access_and_binding_are_rejected(agreement_app):
    client, headers, app, original = agreement_app
    row = publish(client, headers, create(client, headers))
    switched = data(client.post("/system/auth/select-app", headers=headers, json={"app_id": original}))
    other = {"Authorization": f"Bearer {switched['access_token']}"}
    assert client.get(f"{BASE}/{row['id']}", headers=other).status_code == 404
    assert client.get(f"{BASE}/{row['id']}/versions", headers=other).status_code == 404
    assert client.post(f"{BASE}/scenes", headers=other, json={"code": f"foreign_{uuid4().hex[:8]}", "name": "跨客户端", "agreement_ids": [row["id"]]}).status_code == 404
    assert client.get(BASE).status_code in (401, 403)
    records = data(client.get(BASE, headers=other, params={"app_id": app["id"]}))
    assert all(item["app_id"] != app["id"] for item in records["items"])


def test_delete_archive_and_empty_publication(agreement_app):
    client, headers, app, _ = agreement_app
    blank = data(client.post(BASE, headers=headers, json={"code": "empty_text", "title": "空协议", "content": "<p>&nbsp;</p>", "change_summary": "初始化"}))
    assert client.post(f"{BASE}/{blank['id']}/publish", headers=headers, json={"revision": blank["revision"]}).status_code == 400
    data(client.delete(f"{BASE}/{blank['id']}", headers=headers, params={"revision": blank["revision"]}))
    assert client.get(f"{BASE}/{blank['id']}", headers=headers).status_code == 404
    row = publish(client, headers, create(client, headers))
    assert client.delete(f"{BASE}/{row['id']}", headers=headers, params={"revision": row["revision"]}).status_code == 400
    data(client.post(f"{BASE}/{row['id']}/archive", headers=headers, json={"revision": row["revision"]}))
    assert client.get(f"/public/client-apps/{app['code']}/agreements/{row['code']}").status_code == 404

    archived = data(client.get(f"{BASE}/{row['id']}", headers=headers))
    restored = data(client.post(f"{BASE}/{row['id']}/unarchive", headers=headers, json={"revision": archived["revision"]}))
    assert restored["status"] == "draft"
    assert client.get(f"/public/client-apps/{app['code']}/agreements/{row['code']}").status_code == 404


@pytest.mark.parametrize("plan_type,scene_code", [("subscription", "membership_purchase"), ("credit_pack", "credit_purchase")])
async def test_purchase_requires_exact_scene_versions_and_records_once(test_client, plan_type, scene_code):
    from sqlalchemy import func, select

    from app.api.v1.module_agreement.model import AgreementAcceptanceModel
    from app.api.v1.module_agreement.public_service import PublicAgreementService
    from app.api.v1.module_agreement.schema import AcceptanceInput, DraftInput, SceneInput
    from app.api.v1.module_agreement.service import AgreementService
    from app.api.v1.module_billing.model import AppCatalogPlanModel, PricingStandardVersionModel
    from app.api.v1.module_client.app.model import ClientAppModel
    from app.api.v1.module_client.user.model import ClientUserModel
    from app.api.v1.module_payment.order.schema import PaymentOrderCreate
    from app.api.v1.module_payment.order.service import PaymentOrderService
    from app.core.base_schema import AuthSchema, CoreUserSchema
    from app.core.database import async_db_session
    from app.core.exceptions import CustomException

    async with async_db_session() as db:
        try:
            app = ClientAppModel(service_mode="credits_only", code=f"purchase_{uuid4().hex[:10]}", name="协议购买验证", status="active")
            db.add(app)
            await db.flush()
            user = ClientUserModel(app_id=app.id, username="purchase_user", password_hash="test-only", status="active")
            db.add(user)
            await db.flush()
            staff = AuthSchema(app_id=app.id, user=CoreUserSchema(id=1, username="admin", is_superuser=True), actor_type="staff")
            management = AgreementService(staff, db)
            agreement = await management.save(DraftInput(code="purchase_terms", title="购买协议", content="<p>购买条款</p>", change_summary="首版"))
            agreement = await management.publish(agreement.id, agreement.revision)
            await management.save_scene(SceneInput(code=scene_code, name="购买", agreement_ids=[agreement.id]))
            version = await db.scalar(select(PricingStandardVersionModel).where(PricingStandardVersionModel.status == "published"))
            plan = AppCatalogPlanModel(
                app_id=app.id,
                pricing_version_id=version.id,
                code=f"free_{uuid4().hex[:8]}",
                name="零元测试",
                plan_type=plan_type,
                one_time_price_fen=0,
                recurring_price_fen=0,
                total_credits=100,
                release_plan=[{"offset_day": 0, "amount": 100}],
                benefits=[],
                requires_active_subscription=False,
                status="on_sale",
            )
            db.add(plan)
            await db.flush()
            client_auth = AuthSchema(app_id=app.id, user=CoreUserSchema(id=user.id, username=user.username), actor_type="client")
            orders = PaymentOrderService(client_auth, db)
            request = PaymentOrderCreate(catalog_plan_id=plan.id, provider="wechat", idempotency_key=uuid4().hex)
            with pytest.raises(CustomException, match="阅读并同意"):
                await orders.create(request)
            scene = await PublicAgreementService(db, app.id).scene(scene_code)
            request.agreement_acceptance = AcceptanceInput(scene_revision=scene.revision, version_ids=[999999])
            with pytest.raises(CustomException, match="协议已更新"):
                await orders.create(request)
            request.agreement_acceptance = AcceptanceInput(scene_revision=scene.revision, version_ids=[a.version_id for a in scene.agreements])
            first = await orders.create(request)
            second = await orders.create(request)
            assert first.id == second.id and first.status == "paid"
            assert await db.scalar(select(func.count()).select_from(AgreementAcceptanceModel).where(AgreementAcceptanceModel.app_id == app.id)) == 1
        finally:
            await db.rollback()
