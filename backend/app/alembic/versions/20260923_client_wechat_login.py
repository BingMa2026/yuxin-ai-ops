"""Bind client users to a website-application WeChat identity."""

import sqlalchemy as sa
from alembic import op

revision = "20260923_client_wechat_login"
down_revision = "20260914_generation_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client_user", sa.Column("wechat_openid", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_client_user_app_wechat_openid", "client_user", ["app_id", "wechat_openid"])


def downgrade() -> None:
    op.drop_constraint("uq_client_user_app_wechat_openid", "client_user", type_="unique")
    op.drop_column("client_user", "wechat_openid")
