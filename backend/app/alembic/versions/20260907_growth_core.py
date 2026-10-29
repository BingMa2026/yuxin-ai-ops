"""Versioned growth policies, referral evidence and reward accounting."""

import sqlalchemy as sa
from alembic import op

revision = "20260907_growth_core"
down_revision = "20260907_model_default_routes"
branch_labels = None
depends_on = None


# Development startup historically calls create_all before Alembic. Adopt those
# tables without dropping data, and explicitly backfill only new zero balances.
_ZERO_COLUMNS = {("growth_profile", "credit_debt"), ("growth_reward", "reversed_amount"), ("growth_cash_ledger", "frozen_delta"), ("growth_cash_ledger", "debt_delta")}


def _add_column(table_name, column):
    if not op.get_context().as_sql:
        inspector = sa.inspect(op.get_bind())
        if column.name in {c["name"] for c in inspector.get_columns(table_name)}:
            return
        if not column.nullable and (table_name, column.name) in _ZERO_COLUMNS:
            column.server_default = sa.DefaultClause(sa.text("0"))
    op.add_column(table_name, column)
    if not op.get_context().as_sql and (table_name, column.name) in _ZERO_COLUMNS and op.get_bind().dialect.name != "sqlite":
        op.alter_column(table_name, column.name, server_default=None)


def _create_table(name, *columns, **kwargs):
    if op.get_context().as_sql or not sa.inspect(op.get_bind()).has_table(name):
        return op.create_table(name, *columns, **kwargs)
    for column in columns:
        if isinstance(column, sa.Column):
            _add_column(name, column)


def _create_index(name, table_name, columns, **kwargs):
    if not op.get_context().as_sql:
        existing = {index["name"]: index for index in sa.inspect(op.get_bind()).get_indexes(table_name)}
        if name in existing:
            if existing[name]["column_names"] != columns or bool(existing[name]["unique"]) != bool(kwargs.get("unique")):
                raise RuntimeError(f"Existing index {name} does not match the growth migration")
            return
    op.create_index(name, table_name, columns, **kwargs)


def upgrade():
    _create_table(
        "growth_policy",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operator_id", sa.Integer(), nullable=True),
        sa.Column("used_credits", sa.BigInteger(), nullable=False),
        sa.Column("used_cash_fen", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["sys_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "key", "version", name="uq_growth_policy_version"),
    )
    _create_index(op.f("ix_growth_policy_created_time"), "growth_policy", ["created_time"], unique=False)
    _create_index("ix_growth_policy_current", "growth_policy", ["app_id", "kind", "status", "effective_at"], unique=False)
    _create_index(op.f("ix_growth_policy_id"), "growth_policy", ["id"], unique=False)
    _create_index(op.f("ix_growth_policy_is_deleted"), "growth_policy", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_policy_uuid"), "growth_policy", ["uuid"], unique=True)
    _create_table(
        "growth_cash_account",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("available", sa.BigInteger(), nullable=False),
        sa.Column("frozen", sa.BigInteger(), nullable=False),
        sa.Column("debt", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.CheckConstraint("available >= 0 AND frozen >= 0 AND debt >= 0", name="ck_growth_cash_balances"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["client_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "user_id", name="uq_growth_cash_user"),
    )
    _create_index(op.f("ix_growth_cash_account_created_time"), "growth_cash_account", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_cash_account_id"), "growth_cash_account", ["id"], unique=False)
    _create_index(op.f("ix_growth_cash_account_is_deleted"), "growth_cash_account", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_cash_account_uuid"), "growth_cash_account", ["uuid"], unique=True)
    _create_table(
        "growth_cash_ledger",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entry_key", sa.String(length=128), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("frozen_delta", sa.BigInteger(), nullable=False),
        sa.Column("debt_delta", sa.BigInteger(), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["client_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "entry_key", name="uq_growth_cash_entry"),
    )
    _create_index(op.f("ix_growth_cash_ledger_created_time"), "growth_cash_ledger", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_cash_ledger_id"), "growth_cash_ledger", ["id"], unique=False)
    _create_index(op.f("ix_growth_cash_ledger_is_deleted"), "growth_cash_ledger", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_cash_ledger_uuid"), "growth_cash_ledger", ["uuid"], unique=True)
    _create_index("ix_growth_cash_user", "growth_cash_ledger", ["app_id", "user_id", "created_time"], unique=False)
    _create_table(
        "growth_event",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["client_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "event_key", name="uq_growth_event_key"),
    )
    _create_index(op.f("ix_growth_event_created_time"), "growth_event", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_event_id"), "growth_event", ["id"], unique=False)
    _create_index(op.f("ix_growth_event_is_deleted"), "growth_event", ["is_deleted"], unique=False)
    _create_index("ix_growth_event_pending", "growth_event", ["status", "created_time"], unique=False)
    _create_index(op.f("ix_growth_event_uuid"), "growth_event", ["uuid"], unique=True)
    _create_table(
        "growth_gift",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("allocations", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.CheckConstraint("sender_id != recipient_id AND amount > 0", name="ck_growth_gift_valid"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["growth_policy.id"],
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["client_user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"],
            ["client_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "sender_id", "idempotency_key", name="uq_growth_gift_once"),
    )
    _create_index(op.f("ix_growth_gift_created_time"), "growth_gift", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_gift_id"), "growth_gift", ["id"], unique=False)
    _create_index(op.f("ix_growth_gift_is_deleted"), "growth_gift", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_gift_uuid"), "growth_gift", ["uuid"], unique=True)
    _create_table(
        "growth_gift_allowance",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("baseline", sa.BigInteger(), nullable=False),
        sa.Column("used", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["client_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "user_id", "month", name="uq_growth_gift_month"),
    )
    _create_index(op.f("ix_growth_gift_allowance_created_time"), "growth_gift_allowance", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_gift_allowance_id"), "growth_gift_allowance", ["id"], unique=False)
    _create_index(op.f("ix_growth_gift_allowance_is_deleted"), "growth_gift_allowance", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_gift_allowance_uuid"), "growth_gift_allowance", ["uuid"], unique=True)
    _create_table(
        "growth_grade_evaluation",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.Column("track", sa.String(length=16), nullable=False),
        sa.Column("period_key", sa.String(length=32), nullable=False),
        sa.Column("old_grade", sa.String(length=8), nullable=False),
        sa.Column("new_grade", sa.String(length=8), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["growth_policy.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["client_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "user_id", "track", "period_key", "policy_id", name="uq_growth_grade_period"),
    )
    _create_index(op.f("ix_growth_grade_evaluation_created_time"), "growth_grade_evaluation", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_grade_evaluation_id"), "growth_grade_evaluation", ["id"], unique=False)
    _create_index(op.f("ix_growth_grade_evaluation_is_deleted"), "growth_grade_evaluation", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_grade_evaluation_uuid"), "growth_grade_evaluation", ["uuid"], unique=True)
    _create_index("ix_growth_grade_user", "growth_grade_evaluation", ["app_id", "user_id", "track"], unique=False)
    _create_table(
        "growth_payout_account",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("encrypted_details", sa.Text(), nullable=False),
        sa.Column("masked_label", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["client_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "user_id", "provider", name="uq_growth_payout_account"),
    )
    _create_index(op.f("ix_growth_payout_account_created_time"), "growth_payout_account", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_payout_account_id"), "growth_payout_account", ["id"], unique=False)
    _create_index(op.f("ix_growth_payout_account_is_deleted"), "growth_payout_account", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_payout_account_uuid"), "growth_payout_account", ["uuid"], unique=True)
    _create_table(
        "growth_profile",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("invite_code", sa.String(length=24), nullable=False),
        sa.Column("usage_grade", sa.String(length=8), nullable=False),
        sa.Column("promotion_grade", sa.String(length=8), nullable=False),
        sa.Column("first_task_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluations", sa.JSON(), nullable=False),
        sa.Column("credit_debt", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["client_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "user_id", name="uq_growth_profile_user"),
        sa.UniqueConstraint("invite_code", name="uq_growth_invite_code"),
    )
    _create_index(op.f("ix_growth_profile_created_time"), "growth_profile", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_profile_id"), "growth_profile", ["id"], unique=False)
    _create_index(op.f("ix_growth_profile_is_deleted"), "growth_profile", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_profile_uuid"), "growth_profile", ["uuid"], unique=True)
    _create_table(
        "growth_referral",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("inviter_id", sa.Integer(), nullable=False),
        sa.Column("invitee_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("risk_status", sa.String(length=20), nullable=False),
        sa.Column("risk_reason", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.CheckConstraint("inviter_id != invitee_id", name="ck_growth_referral_not_self"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["invitee_id"],
            ["client_user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["inviter_id"],
            ["client_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "invitee_id", name="uq_growth_referral_invitee"),
    )
    _create_index(op.f("ix_growth_referral_created_time"), "growth_referral", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_referral_id"), "growth_referral", ["id"], unique=False)
    _create_index("ix_growth_referral_inviter", "growth_referral", ["app_id", "inviter_id", "bound_at"], unique=False)
    _create_index(op.f("ix_growth_referral_is_deleted"), "growth_referral", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_referral_uuid"), "growth_referral", ["uuid"], unique=True)
    _create_table(
        "growth_task",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("local_task_id", sa.String(length=128), nullable=False),
        sa.Column("project_ref", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("artifact_ref", sa.String(length=128), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_reason", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["client_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "user_id", "local_task_id", name="uq_growth_task_local"),
    )
    _create_index(op.f("ix_growth_task_created_time"), "growth_task", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_task_id"), "growth_task", ["id"], unique=False)
    _create_index(op.f("ix_growth_task_is_deleted"), "growth_task", ["is_deleted"], unique=False)
    _create_index("ix_growth_task_user", "growth_task", ["app_id", "user_id", "status"], unique=False)
    _create_index(op.f("ix_growth_task_uuid"), "growth_task", ["uuid"], unique=True)
    _create_table(
        "growth_reward",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.Column("entitlement_key", sa.String(length=160), nullable=False),
        sa.Column("asset", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("release_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_amount", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.CheckConstraint("amount >= 0", name="ck_growth_reward_amount"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["growth_event.id"],
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["growth_policy.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["client_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "entitlement_key", "user_id", "asset", name="uq_growth_reward_once"),
    )
    _create_index(op.f("ix_growth_reward_created_time"), "growth_reward", ["created_time"], unique=False)
    _create_index("ix_growth_reward_due", "growth_reward", ["status", "release_at"], unique=False)
    _create_index(op.f("ix_growth_reward_id"), "growth_reward", ["id"], unique=False)
    _create_index(op.f("ix_growth_reward_is_deleted"), "growth_reward", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_reward_uuid"), "growth_reward", ["uuid"], unique=True)
    _create_table(
        "growth_task_evidence",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("business_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["growth_task.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["client_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "request_id", name="uq_growth_evidence_request"),
    )
    _create_index(op.f("ix_growth_task_evidence_created_time"), "growth_task_evidence", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_task_evidence_id"), "growth_task_evidence", ["id"], unique=False)
    _create_index(op.f("ix_growth_task_evidence_is_deleted"), "growth_task_evidence", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_task_evidence_uuid"), "growth_task_evidence", ["uuid"], unique=True)
    _create_table(
        "growth_withdrawal",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("out_bill_no", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("amount_fen", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("payee_snapshot", sa.Text(), nullable=False),
        sa.Column("provider_bill_no", sa.String(length=128), nullable=True),
        sa.Column("confirmation_package", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.CheckConstraint("amount_fen > 0", name="ck_growth_withdrawal_amount"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["growth_payout_account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["client_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", "user_id", "idempotency_key", name="uq_growth_withdrawal_once"),
        sa.UniqueConstraint("out_bill_no", name="uq_growth_payout_bill"),
    )
    _create_index(op.f("ix_growth_withdrawal_created_time"), "growth_withdrawal", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_withdrawal_id"), "growth_withdrawal", ["id"], unique=False)
    _create_index(op.f("ix_growth_withdrawal_is_deleted"), "growth_withdrawal", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_withdrawal_uuid"), "growth_withdrawal", ["uuid"], unique=True)
    _create_table(
        "growth_payout_attempt",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("withdrawal_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["withdrawal_id"],
            ["growth_withdrawal.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("ix_growth_payout_attempt", "growth_payout_attempt", ["app_id", "withdrawal_id"], unique=False)
    _create_index(op.f("ix_growth_payout_attempt_created_time"), "growth_payout_attempt", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_payout_attempt_id"), "growth_payout_attempt", ["id"], unique=False)
    _create_index(op.f("ix_growth_payout_attempt_is_deleted"), "growth_payout_attempt", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_payout_attempt_uuid"), "growth_payout_attempt", ["uuid"], unique=True)
    _create_table(
        "growth_payout_link",
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("withdrawal_id", sa.Integer(), nullable=True),
        sa.Column("encrypted_payload", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["client_app.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["client_user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["withdrawal_id"],
            ["growth_withdrawal.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_growth_payout_link_token"),
    )
    _create_index(op.f("ix_growth_payout_link_created_time"), "growth_payout_link", ["created_time"], unique=False)
    _create_index(op.f("ix_growth_payout_link_id"), "growth_payout_link", ["id"], unique=False)
    _create_index(op.f("ix_growth_payout_link_is_deleted"), "growth_payout_link", ["is_deleted"], unique=False)
    _create_index(op.f("ix_growth_payout_link_uuid"), "growth_payout_link", ["uuid"], unique=True)
    _add_column("client_support_ticket", sa.Column("value_grade", sa.String(length=1), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    op.drop_column("client_support_ticket", "value_grade")
    op.drop_table("growth_payout_link")
    op.drop_table("growth_payout_attempt")
    op.drop_table("growth_withdrawal")
    op.drop_table("growth_task_evidence")
    op.drop_table("growth_reward")
    op.drop_table("growth_task")
    op.drop_table("growth_referral")
    op.drop_table("growth_profile")
    op.drop_table("growth_payout_account")
    op.drop_table("growth_grade_evaluation")
    op.drop_table("growth_gift_allowance")
    op.drop_table("growth_gift")
    op.drop_table("growth_event")
    op.drop_table("growth_cash_ledger")
    op.drop_table("growth_cash_account")
    op.drop_table("growth_policy")
