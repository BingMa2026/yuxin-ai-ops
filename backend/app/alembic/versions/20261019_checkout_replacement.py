"""Link checkout replacements without changing historical payment states."""

import sqlalchemy as sa
from alembic import op

revision = "20261019_checkout_replace"
down_revision = "20261014_payment_cancel"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payment_order", sa.Column("replaces_order_no", sa.String(64), nullable=True))
    op.add_column("payment_order", sa.Column("replaced_by_order_no", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("payment_order", "replaced_by_order_no")
    op.drop_column("payment_order", "replaces_order_no")
