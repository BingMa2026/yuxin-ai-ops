"""Mark verified client mobile identities without trusting legacy profile numbers."""

import sqlalchemy as sa
from alembic import op

revision = "20261009_client_mobile_identity"
down_revision = "20260928_payment_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("client_user", sa.Column("mobile_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_client_user_verified_mobile",
        "client_user",
        ["app_id", "mobile"],
        unique=True,
        postgresql_where=sa.text("mobile_verified_at IS NOT NULL AND is_deleted = false"),
        sqlite_where=sa.text("mobile_verified_at IS NOT NULL AND is_deleted = 0"),
    )


def downgrade():
    op.drop_index("uq_client_user_verified_mobile", table_name="client_user")
    op.drop_column("client_user", "mobile_verified_at")
