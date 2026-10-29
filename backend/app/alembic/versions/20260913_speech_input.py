"""Per-client speech input configuration and duration-based usage audit."""

import importlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import sqlalchemy as sa
from alembic import op

revision = "20260913_speech_input"
down_revision = "20260911_agreements"
branch_labels = None
depends_on = None


def _base():
    return [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(64), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_time", sa.DateTime(timezone=True)),
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
    ]


def upgrade():
    bind = op.get_bind()
    for name, kind in (("speech_protocol", sa.String(40)), ("speech_pricing", sa.JSON())):
        if op.get_context().as_sql or name not in {c["name"] for c in sa.inspect(bind).get_columns("model_catalog")}:
            op.add_column("model_catalog", sa.Column(name, kind, nullable=True))
    helpers = importlib.import_module("app.alembic.versions.20260911_agreements")
    # An earlier ORM startup could create this unused per-app price column.
    # Prices now belong to the model catalog; discard only an empty legacy field.
    if not op.get_context().as_sql and sa.inspect(bind).has_table("app_speech_config"):
        legacy = next((c for c in sa.inspect(bind).get_columns("app_speech_config") if c["name"] == "cost_per_minute"), None)
        if legacy:
            if not isinstance(legacy["type"], sa.Numeric) or not legacy["nullable"]:
                raise RuntimeError("Unexpected legacy app_speech_config.cost_per_minute schema")
            if bind.scalar(sa.text("SELECT COUNT(*) FROM app_speech_config WHERE cost_per_minute IS NOT NULL")):
                raise RuntimeError("Legacy app speech prices contain data; explicit reconciliation is required")
            op.drop_column("app_speech_config", "cost_per_minute")
    helpers._create_table(
        "app_speech_config",
        *_base(),
        sa.Column("catalog_model_id", sa.Integer(), sa.ForeignKey("model_catalog.id", ondelete="RESTRICT")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("daily_limit_seconds", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("app_id", name="uq_speech_config_app"),
    )
    helpers._create_table(
        "speech_usage",
        *_base(),
        sa.Column("catalog_model_id", sa.Integer(), sa.ForeignKey("model_catalog.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("cost_per_minute", sa.Numeric(16, 8)),
        sa.Column("estimated_cost_yuan", sa.Numeric(16, 8)),
        sa.Column("error_category", sa.String(32)),
        sa.UniqueConstraint("app_id", "user_id", "request_id", name="uq_speech_request"),
    )
    for table in ("app_speech_config", "speech_usage"):
        for field in ("id", "uuid", "is_deleted", "created_time"):
            helpers._create_index(f"ix_{table}_{field}", table, [field], unique=field == "uuid")
    helpers._create_index("ix_speech_user_time", "speech_usage", ["app_id", "user_id", "created_time"])
    if not op.get_context().as_sql:
        snapshot = json.loads(Path(__file__).with_name("20260913_speech_prices.json").read_text(encoding="utf-8"))
        catalog = sa.table("model_catalog", sa.column("id", sa.Integer), sa.column("speech_protocol", sa.String), sa.column("speech_pricing", sa.JSON), sa.column("supports_stream", sa.Boolean))
        rows = bind.execute(
            sa.text(
                "SELECT m.id, m.provider_model_id, m.speech_protocol, m.speech_pricing, a.endpoint FROM model_catalog m JOIN model_provider_account a ON a.id=m.provider_account_id WHERE m.is_deleted=false"
            )
        ).mappings()
        for row in rows:
            name = row["provider_model_id"].lower()
            host = urlsplit(row["endpoint"]).hostname or ""
            changes = {}
            if not row["speech_pricing"] and (host == "dashscope.aliyuncs.com" or host.endswith(".cn-beijing.maas.aliyuncs.com")) and name in snapshot:
                changes["speech_pricing"] = snapshot[name]
            if not row["speech_protocol"]:
                if name.startswith("qwen3-asr-flash-realtime"):
                    changes["speech_protocol"] = "qwen_realtime"
                elif name.startswith("qwen3-asr-flash") and "filetrans" not in name:
                    changes["speech_protocol"] = "qwen_asr"
                elif name == "qwen-audio-3.0-asr-flash" or name.startswith("fun-asr-flash-2026"):
                    changes["speech_protocol"] = "dashscope_asr"
            if changes.get("speech_protocol"):
                changes["supports_stream"] = False
            if changes:
                bind.execute(catalog.update().where(catalog.c.id == row["id"]).values(**changes))


def downgrade():
    op.drop_column("model_catalog", "speech_pricing")
    op.drop_column("model_catalog", "speech_protocol")
    op.drop_table("speech_usage")
    op.drop_table("app_speech_config")
