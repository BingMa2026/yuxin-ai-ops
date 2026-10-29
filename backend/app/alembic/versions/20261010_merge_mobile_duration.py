"""Merge client mobile identity and subscription duration migration branches."""

revision = "20261010_merge_mobile_duration"
down_revision = ("20261009_client_mobile_identity", "20261010_duration_adjustment")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
