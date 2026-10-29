"""Bootstrap business routes for existing active client model bindings."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_model_default_routes"
down_revision: str | None = "20260907_model_menus"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROUTES = (
    ("chat_default", "默认聊天"),
    ("document_intelligence", "文档理解"),
    ("semantic_review", "语义审核"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("app_model_binding") or not inspector.has_table("app_model_route"):
        return
    metadata = sa.MetaData()
    binding = sa.Table("app_model_binding", metadata, autoload_with=bind)
    route = sa.Table("app_model_route", metadata, autoload_with=bind)
    rows = bind.execute(
        sa.select(binding).where(binding.c.status == "active", binding.c.is_deleted.is_(False)).order_by(binding.c.app_id, binding.c.is_default.desc(), binding.c.order, binding.c.id)
    ).mappings()
    selected: dict[int, dict] = {}
    for row in rows:
        selected.setdefault(int(row["app_id"]), row)

    now = datetime.now(UTC)
    for app_id, primary in selected.items():
        existing = set(
            bind.execute(
                sa.select(route.c.business_code).where(
                    route.c.app_id == app_id,
                    route.c.is_deleted.is_(False),
                )
            ).scalars()
        )
        for business_code, name in _ROUTES:
            if business_code in existing:
                continue
            bind.execute(
                route.insert().values(
                    uuid=str(uuid4()),
                    is_deleted=False,
                    created_time=now,
                    updated_time=now,
                    app_id=app_id,
                    business_code=business_code,
                    name=name,
                    primary_binding_id=primary["id"],
                    fallback_binding_ids=[],
                    timeout_seconds=120,
                    max_output_tokens=8192,
                    allow_tools=True,
                    allow_user_model=True,
                    status="active",
                    created_id=primary.get("created_id"),
                    updated_id=primary.get("updated_id"),
                )
            )


def downgrade() -> None:
    # These routes are immediately editable business data.  A downgrade must
    # not delete operator changes or routes that have already served traffic.
    pass
