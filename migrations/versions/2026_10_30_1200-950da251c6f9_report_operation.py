"""Report operation.

Adds ``registration_reports.operation`` so the outbox also carries
``holder.profile_updated`` reports. Existing rows were all
``holder.registered``, which the server default fills in.

Revision ID: 950da251c6f9
Revises: db62a6b1118d
Create Date: 2026-10-30 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "950da251c6f9"
down_revision: str | Sequence[str] | None = "db62a6b1118d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("registration_reports") as batch_op:
        batch_op.add_column(
            sa.Column(
                "operation",
                sa.String(length=40),
                nullable=False,
                server_default="holder.registered",
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("registration_reports") as batch_op:
        batch_op.drop_column("operation")
