import importlib
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError

from app.api.v1.module_billing.model import AppCatalogPlanModel, PricingStandardVersionModel
from app.api.v1.module_billing.schema import CatalogPlanCreateSchema
from app.api.v1.module_billing.service import CatalogService
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException


async def test_recreate_deleted_trial_keeps_history_and_rejects_live_duplicates(test_client):
    del test_client
    async with async_db_session() as db:
        async with db.begin():
            version_id = await db.scalar(select(PricingStandardVersionModel.id).where(PricingStandardVersionModel.status == "published", PricingStandardVersionModel.is_deleted == False))
            data = CatalogPlanCreateSchema(
                pricing_version_id=version_id,
                code=f"trial_{uuid4().hex[:8]}",
                name="体验版",
                one_time_price_fen=0,
                recurring_price_fen=0,
                benefit_period_days=7,
                credit_valid_days=7,
                total_credits=300,
                release_plan=[{"offset_day": 0, "amount": 300}],
            )
            service = CatalogService(AuthSchema(user=CoreUserSchema(id=1, username="admin"), app_id=1, actor_type="staff"), db)
            original = await service.create(data)
            old = await db.get(AppCatalogPlanModel, original.id)
            old.is_deleted = True
            await db.flush()
            created = await service.create(data)
            assert created.id != original.id and created.code == original.code
            assert created.status == "draft" and created.total_credits == 300
            assert created.release_plan[0]["account_type"] == "current_cycle"
            await db.refresh(old)
            assert old.is_deleted and old.code == original.code and old.total_credits == 300
            with pytest.raises(CustomException, match="相同刊例编码"):
                await service.create(data)
            await db.rollback()


def test_catalog_code_migration_retains_history_and_client_uniqueness():
    migration = importlib.import_module("app.alembic.versions.20260909_catalog_codes")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE app_catalog_plan (id INTEGER PRIMARY KEY, app_id INTEGER NOT NULL, code VARCHAR(64) NOT NULL, is_deleted BOOLEAN NOT NULL, CONSTRAINT uq_app_catalog_plan_app_code UNIQUE(app_id,code))"
            )
        )
        conn.execute(text("INSERT INTO app_catalog_plan VALUES (1,1,'trial',1)"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.upgrade()
            conn.execute(text("INSERT INTO app_catalog_plan VALUES (2,1,'trial',0),(3,2,'trial',0)"))
            with pytest.raises(IntegrityError):
                conn.execute(text("INSERT INTO app_catalog_plan VALUES (4,1,'trial',0)"))
            with pytest.raises(RuntimeError, match="重复编码"):
                migration.downgrade()
            conn.execute(text("DELETE FROM app_catalog_plan WHERE id=2"))
            migration.downgrade()
            with pytest.raises(IntegrityError):
                conn.execute(text("INSERT INTO app_catalog_plan VALUES (2,1,'trial',0)"))
    engine.dispose()
