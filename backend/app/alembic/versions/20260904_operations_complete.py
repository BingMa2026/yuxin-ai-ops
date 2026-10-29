"""预算中心与用户运营完整业务模型。

Revision ID: 20260904_operations_complete
Revises: 20260903_client_app_order
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_operations_complete"
down_revision: str | None = "20260903_client_app_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_PRIORITY = ["activity_reward", "current_cycle", "monthly_reserve", "traffic_pack", "enterprise_pool", "manual"]
DEFAULT_LEVEL_RULES = {
    "dimensions": [
        {"key": "total_paid_fen", "label": "累计支付", "weight": 30, "cap": 500000},
        {"key": "active_days_30d", "label": "近30日活跃天数", "weight": 20, "cap": 20},
        {"key": "model_calls_30d", "label": "近30日模型调用", "weight": 20, "cap": 200},
        {"key": "credits_used_30d", "label": "近30日积分消耗", "weight": 20, "cap": 100000},
        {"key": "feedback_contribution", "label": "有效反馈", "weight": 10, "cap": 5},
    ],
    "levels": [
        {"code": "LV1", "name": "初始用户", "min_score": 0},
        {"code": "LV2", "name": "活跃用户", "min_score": 20},
        {"code": "LV3", "name": "成长用户", "min_score": 40},
        {"code": "LV4", "name": "高价值用户", "min_score": 60},
        {"code": "LV5", "name": "核心用户", "min_score": 80},
    ],
}


def _inspector():
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    inspector = _inspector()
    return inspector.has_table(table) and any(item["name"] == column for item in inspector.get_columns(table))


def _add_column(table: str, column: sa.Column) -> None:
    if not _has_column(table, column.name):
        op.add_column(table, column)


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(64), nullable=False, unique=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True),
    ]


def _audit() -> list[sa.Column]:
    return [
        sa.Column("created_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True),
        sa.Column("updated_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True),
        sa.Column("deleted_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True),
    ]


def _create(name: str, *columns, constraints=(), indexes=(), audit=False, comment: str) -> None:
    if _inspector().has_table(name):
        return
    op.create_table(name, *_base(), *columns, *(_audit() if audit else []), *constraints, comment=comment)
    for index_name, fields in indexes:
        op.create_index(index_name, name, fields)


def upgrade() -> None:
    # Repair a table created before the model-gateway migration was applied.
    _add_column("model_usage", sa.Column("provider_cost_yuan", sa.Numeric(18, 8), nullable=False, server_default="0"))

    _add_column("pricing_standard_version", sa.Column("credits_per_yuan", sa.Integer(), nullable=False, server_default="1000"))
    _add_column("pricing_standard_version", sa.Column("subscription_cycle_days", sa.Integer(), nullable=False, server_default="30"))
    _add_column("pricing_standard_version", sa.Column("renewal_discount_rate", sa.Numeric(7, 4), nullable=False, server_default="0.9"))
    _add_column("pricing_standard_version", sa.Column("margin_floor", sa.Numeric(7, 4), nullable=False, server_default="25"))
    _add_column("pricing_standard_version", sa.Column("account_priority", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    priority_json = sa.JSON().bind_processor(op.get_bind().dialect)(DEFAULT_PRIORITY)
    op.execute(sa.text("UPDATE pricing_standard_version SET margin_baseline = 60 WHERE margin_baseline IS NULL OR margin_baseline = 0"))
    op.execute(sa.text("UPDATE pricing_standard_version SET account_priority = CAST(:value AS json) WHERE account_priority IS NULL OR account_priority::jsonb = '[]'::jsonb").bindparams(value=priority_json))

    _add_column("pricing_plan_template", sa.Column("plan_type", sa.String(20), nullable=False, server_default="subscription"))
    _add_column("pricing_plan_template", sa.Column("benefits", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    _add_column("pricing_plan_template", sa.Column("requires_active_subscription", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column("app_catalog_plan", sa.Column("plan_type", sa.String(20), nullable=False, server_default="subscription"))
    _add_column("app_catalog_plan", sa.Column("requires_active_subscription", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column("app_catalog_plan", sa.Column("cost_budget_yuan", sa.Numeric(18, 4), nullable=True))

    _add_column("app_pricing_strategy", sa.Column("version", sa.String(32), nullable=True))
    _add_column("app_pricing_strategy", sa.Column("pricing_version_id", sa.Integer(), sa.ForeignKey("pricing_standard_version.id", ondelete="RESTRICT"), nullable=True))
    _add_column("app_pricing_strategy", sa.Column("scope_type", sa.String(20), nullable=False, server_default="all"))
    _add_column("app_pricing_strategy", sa.Column("scope_value", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    _add_column("app_pricing_strategy", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE app_pricing_strategy SET version = CONCAT('LEGACY-', id) WHERE version IS NULL")
    op.execute("UPDATE app_pricing_strategy s SET pricing_version_id = p.pricing_version_id FROM app_catalog_plan p WHERE s.catalog_plan_id = p.id AND s.pricing_version_id IS NULL")

    _create(
        "app_pricing_strategy_item",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("strategy_id", sa.Integer(), sa.ForeignKey("app_pricing_strategy.id", ondelete="CASCADE"), nullable=False),
        sa.Column("catalog_plan_id", sa.Integer(), sa.ForeignKey("app_catalog_plan.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("purchase_type", sa.String(20), nullable=False, server_default="all"),
        sa.Column("discount_rate", sa.Numeric(7, 4), nullable=False, server_default="1"),
        sa.Column("execution_price_fen", sa.Integer(), nullable=False),
        sa.Column("margin_rate", sa.Numeric(7, 4), nullable=False),
        sa.Column("allowed_cost_yuan", sa.Numeric(18, 4), nullable=False),
        sa.Column("credits_per_cost_yuan", sa.Numeric(18, 8), nullable=False),
        sa.Column("remark", sa.String(500), nullable=True),
        constraints=(sa.UniqueConstraint("strategy_id", "catalog_plan_id", "purchase_type", name="uq_strategy_item_plan_purchase"),),
        indexes=(("ix_strategy_item_app_strategy", ["app_id", "strategy_id", "is_deleted"]),),
        audit=True,
        comment="定价策略刊例项",
    )
    op.execute("""
        INSERT INTO app_pricing_strategy_item
          (uuid,is_deleted,created_time,updated_time,app_id,strategy_id,catalog_plan_id,purchase_type,discount_rate,
           execution_price_fen,margin_rate,allowed_cost_yuan,credits_per_cost_yuan,created_id,updated_id)
        SELECT md5(random()::text || clock_timestamp()::text),false,s.created_time,s.updated_time,s.app_id,s.id,s.catalog_plan_id,
               s.purchase_type,COALESCE(s.discount_rate, CASE WHEN base_price.price_fen > 0 THEN s.fixed_price_fen::numeric/base_price.price_fen ELSE 1 END),
               COALESCE(s.fixed_price_fen,ROUND(base_price.price_fen*COALESCE(s.discount_rate,1)))::int,
               COALESCE(v.margin_baseline,60),
               GREATEST(0.01,(COALESCE(s.fixed_price_fen,ROUND(base_price.price_fen*COALESCE(s.discount_rate,1)))::numeric/100)*(1-COALESCE(v.margin_baseline,60)/100)),
               p.total_credits/GREATEST(0.01,(COALESCE(s.fixed_price_fen,ROUND(base_price.price_fen*COALESCE(s.discount_rate,1)))::numeric/100)*(1-COALESCE(v.margin_baseline,60)/100)),
               s.created_id,s.updated_id
        FROM app_pricing_strategy s
        JOIN app_catalog_plan p ON p.id=s.catalog_plan_id
        LEFT JOIN pricing_standard_version v ON v.id=p.pricing_version_id
        CROSS JOIN LATERAL (SELECT CASE WHEN s.purchase_type='renewal' THEN p.recurring_price_fen ELSE p.one_time_price_fen END price_fen) base_price
        WHERE NOT EXISTS (SELECT 1 FROM app_pricing_strategy_item i WHERE i.strategy_id=s.id)
    """)

    _add_column("credit_grant", sa.Column("account_type", sa.String(32), nullable=False, server_default="monthly_reserve"))
    _add_column("credit_grant", sa.Column("credits_per_cost_yuan", sa.Numeric(18, 8), nullable=False, server_default="2500"))
    _add_column("credit_grant", sa.Column("pricing_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    _add_column("credit_reservation", sa.Column("estimated_cost_yuan", sa.Numeric(18, 8), nullable=True))
    _add_column("credit_reservation", sa.Column("actual_cost_yuan", sa.Numeric(18, 8), nullable=True))

    _add_column("client_user", sa.Column("level_code", sa.String(8), nullable=False, server_default="LV1"))
    _add_column("client_user", sa.Column("level_score", sa.Numeric(7, 2), nullable=False, server_default="0"))
    _add_column("client_user", sa.Column("level_evaluated_at", sa.DateTime(timezone=True), nullable=True))
    _add_column("client_user", sa.Column("level_metrics", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))

    _create(
        "client_user_level_config",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        constraints=(sa.UniqueConstraint("app_id", name="uq_client_level_config_app"),),
        indexes=(("ix_client_level_config_app_status", ["app_id", "status", "is_deleted"]),),
        audit=True,
        comment="客户端用户等级规则",
    )
    _create(
        "client_user_level_history",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_level", sa.String(8), nullable=True),
        sa.Column("new_level", sa.String(8), nullable=False),
        sa.Column("score", sa.Numeric(7, 2), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        indexes=(("ix_client_level_history_app_user", ["app_id", "user_id", "created_time"]),),
        comment="客户端用户等级变更历史",
    )
    _create(
        "client_user_segment",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        constraints=(sa.UniqueConstraint("app_id", "name", name="uq_client_user_segment_name"),),
        indexes=(("ix_client_user_segment_app_status", ["app_id", "status", "is_deleted"]),),
        audit=True,
        comment="客户端动态用户分群",
    )

    _create(
        "client_support_ticket",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ticket_no", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("assignee_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adopted", sa.Boolean(), nullable=False, server_default=sa.false()),
        constraints=(sa.UniqueConstraint("app_id", "ticket_no", name="uq_client_support_ticket_no"),),
        indexes=(("ix_support_ticket_app_status", ["app_id", "status", "is_deleted"]), ("ix_support_ticket_app_user", ["app_id", "user_id", "created_time"])),
        audit=True,
        comment="客户端工单与反馈",
    )
    _create(
        "client_support_message",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("client_support_ticket.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_type", sa.String(16), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("internal", sa.Boolean(), nullable=False, server_default=sa.false()),
        indexes=(("ix_support_message_app_ticket", ["app_id", "ticket_id", "created_time"]),),
        comment="客户端工单会话",
    )

    _create(
        "client_message_template",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        constraints=(sa.UniqueConstraint("app_id", "name", name="uq_client_message_template_name"),),
        indexes=(("ix_client_message_template_app", ["app_id", "status", "is_deleted"]),),
        audit=True,
        comment="客户端站内消息模板",
    )
    _create(
        "client_message_campaign",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("client_message_template.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("audience_type", sa.String(20), nullable=False),
        sa.Column("audience_value", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("target_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("read_count", sa.Integer(), nullable=False, server_default="0"),
        indexes=(("ix_client_campaign_app_status", ["app_id", "status", "scheduled_at", "is_deleted"]),),
        audit=True,
        comment="客户端站内消息触达任务",
    )
    _create(
        "client_message_delivery",
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("client_message_campaign.id", ondelete="CASCADE"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_type", sa.String(24), nullable=False, server_default="campaign"),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("deep_link", sa.String(500), nullable=True),
        sa.Column("resource_type", sa.String(32), nullable=True),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="delivered"),
        constraints=(sa.UniqueConstraint("campaign_id", "user_id", name="uq_client_message_delivery_campaign_user"),),
        indexes=(("ix_client_message_delivery_inbox", ["app_id", "user_id", "read_at", "created_time"]),),
        comment="客户端站内消息投递",
    )

    # Seed one configurable level policy for every existing client application.
    rules_json = sa.JSON().bind_processor(op.get_bind().dialect)(DEFAULT_LEVEL_RULES)
    op.execute(sa.text("""
        INSERT INTO client_user_level_config
          (uuid,is_deleted,created_time,updated_time,app_id,version,rules,status)
        SELECT md5(random()::text || clock_timestamp()::text),false,now(),now(),id,1,CAST(:rules AS json),'active'
        FROM client_app a
        WHERE a.is_deleted=false AND NOT EXISTS (
          SELECT 1 FROM client_user_level_config c WHERE c.app_id=a.id
        )
    """).bindparams(rules=rules_json))


def downgrade() -> None:
    for table in (
        "client_message_delivery", "client_message_campaign", "client_message_template",
        "client_support_message", "client_support_ticket", "client_user_segment",
        "client_user_level_history", "client_user_level_config", "app_pricing_strategy_item",
    ):
        if _inspector().has_table(table):
            op.drop_table(table)
