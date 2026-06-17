"""composite index for filtered list query

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-17

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_bookings_status", table_name="bookings")
    op.create_index(
        "ix_bookings_status_created_at",
        "bookings",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_bookings_status_created_at", table_name="bookings")
    op.create_index("ix_bookings_status", "bookings", ["status"])
