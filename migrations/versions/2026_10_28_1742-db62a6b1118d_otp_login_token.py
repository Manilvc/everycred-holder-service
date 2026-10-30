"""OTP login token.

Adds the single-use login token that ``otp/verify`` issues so a holder
is signed in right after registering: ``email_otps.login_token_hash``
(HMAC only) and ``email_otps.signed_in_at``.

Revision ID: db62a6b1118d
Revises: 7c1d4e9b2a60
Create Date: 2026-10-28 17:42:30.799201

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "db62a6b1118d"
down_revision: str | Sequence[str] | None = "7c1d4e9b2a60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # batch_alter_table recreates the table on SQLite, which cannot add
    # a constraint in place; on MySQL it issues plain ALTER statements.
    with op.batch_alter_table("email_otps") as batch_op:
        batch_op.add_column(
            sa.Column("login_token_hash", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("signed_in_at", sa.DateTime(), nullable=True)
        )
        batch_op.create_unique_constraint(
            op.f("uq_email_otps_login_token_hash"), ["login_token_hash"]
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("email_otps") as batch_op:
        batch_op.drop_constraint(
            op.f("uq_email_otps_login_token_hash"), type_="unique"
        )
        batch_op.drop_column("signed_in_at")
        batch_op.drop_column("login_token_hash")
