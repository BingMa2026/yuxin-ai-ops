"""Persist cancellation intent until the payment channel confirms its result."""

import sqlalchemy as sa
from alembic import op

revision = "20261014_payment_cancel"
down_revision = "20261013_service_modes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payment_order", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("payment_order", "cancel_requested_at")
