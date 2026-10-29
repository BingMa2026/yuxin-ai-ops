"""Publish the reviewed bid-agent legal documents once, preserving version history.

Run inside the deployed backend container after its database backup:
    python -m tools.publish_bid_agent_agreements --apply
"""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.api.v1.module_agreement.crud import lock_app
from app.api.v1.module_agreement.model import AgreementModel, AgreementSceneModel, AgreementVersionModel
from app.api.v1.module_agreement.schema import DraftInput, SceneInput, has_text
from app.api.v1.module_client.app.model import ClientAppModel
from app.core.database import async_db_session

LEGAL_DIR = Path(__file__).resolve().parents[1] / "legal"
DOCUMENTS = (
    ("user_agreement", "用户服务协议", "user_agreement.html"),
    ("privacy_policy", "隐私政策", "privacy_policy.html"),
    ("paid_services", "订阅与积分服务协议", "paid_services.html"),
)
SCENES = (
    ("auth", "登录注册", ("user_agreement", "privacy_policy"), True),
    ("membership_purchase", "订阅套餐购买", ("paid_services",), True),
    ("credit_purchase", "积分包购买", ("paid_services",), True),
    ("about", "协议与政策", ("user_agreement", "privacy_policy", "paid_services"), False),
)


def validated_documents() -> dict[str, DraftInput]:
    documents = {}
    for code, title, filename in DOCUMENTS:
        document = DraftInput(
            code=code,
            title=title,
            content=(LEGAL_DIR / filename).read_text(encoding="utf-8"),
            change_summary="首次发布正式协议正文",
        )
        if not has_text(document.content):
            raise ValueError(f"empty legal document: {code}")
        documents[code] = document
    return documents


async def publish() -> None:
    documents = validated_documents()
    async with async_db_session() as db:
        async with db.begin():
            app_id = await db.scalar(
                select(ClientAppModel.id).where(
                    ClientAppModel.code == "bid_agent",
                    ClientAppModel.status == "active",
                    ClientAppModel.is_deleted.is_(False),
                )
            )
            if app_id is None:
                raise RuntimeError("active bid_agent client app not found")
            await lock_app(db, app_id)

            existing_docs = {row.code: row for row in (await db.scalars(select(AgreementModel).where(AgreementModel.app_id == app_id))).all()}
            existing_scenes = {row.code: row for row in (await db.scalars(select(AgreementSceneModel).where(AgreementSceneModel.app_id == app_id))).all()}
            legacy = existing_docs.get("cs")
            auth = existing_scenes.get("auth")
            reviewed_auth_ids = [existing_docs[code].id for code in ("user_agreement", "privacy_policy") if code in existing_docs]
            if auth and auth.agreement_ids != reviewed_auth_ids and (not legacy or auth.agreement_ids != [legacy.id]):
                raise RuntimeError("auth scene was changed by an operator; refusing to replace it")

            for code, document in documents.items():
                row = existing_docs.get(code)
                if row:
                    if row.is_deleted or row.status != "published" or row.title != document.title or row.content != document.content or row.current_version != 1:
                        raise RuntimeError(f"{code} differs from the reviewed publication; refusing to overwrite it")
                    continue
                row = AgreementModel(
                    app_id=app_id,
                    code=code,
                    title=document.title,
                    content=document.content,
                    change_summary=document.change_summary,
                    status="published",
                    current_version=1,
                    has_draft=False,
                    revision=2,
                    updated_by=None,
                )
                db.add(row)
                await db.flush()
                db.add(
                    AgreementVersionModel(
                        app_id=app_id,
                        agreement_id=row.id,
                        version=1,
                        title=document.title,
                        content=document.content,
                        change_summary=document.change_summary,
                        published_at=datetime.now(UTC),
                        published_by=None,
                    )
                )
                existing_docs[code] = row
                print(f"published {code} V1")

            for code, name, document_codes, requires_acceptance in SCENES:
                ids = [existing_docs[document_code].id for document_code in document_codes]
                SceneInput(code=code, name=name, agreement_ids=ids, require_acceptance=requires_acceptance)
                row = existing_scenes.get(code)
                if row:
                    if row.is_deleted or (code != "auth" and row.agreement_ids != ids):
                        raise RuntimeError(f"{code} scene differs from reviewed configuration")
                    if row.agreement_ids == ids and row.name == name and row.require_acceptance == requires_acceptance:
                        continue
                    row.name = name
                    row.agreement_ids = ids
                    row.require_acceptance = requires_acceptance
                    row.revision += 1
                    row.updated_by = None
                    print(f"updated {code} scene")
                else:
                    db.add(
                        AgreementSceneModel(
                            app_id=app_id,
                            code=code,
                            name=name,
                            agreement_ids=ids,
                            require_acceptance=requires_acceptance,
                            revision=1,
                            updated_by=None,
                        )
                    )
                    print(f"configured {code} scene")

            if legacy and legacy.status == "published":
                other_scenes = [scene.code for scene in existing_scenes.values() if scene.code != "auth" and legacy.id in scene.agreement_ids and not scene.is_deleted]
                if other_scenes:
                    raise RuntimeError(f"legacy cs document still referenced by {other_scenes}")
                legacy.status = "archived"
                legacy.revision += 1
                legacy.updated_by = None
                print("archived legacy cs placeholder")
    print("agreement publication committed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="required to publish the documents")
    args = parser.parse_args()
    if not args.apply:
        parser.error("pass --apply after reviewing the legal documents and backup")
    asyncio.run(publish())
