"""Holder onboarding: pending invites and registration reports.

``pending_invites`` keeps issuer invites for emails without an account
(the email only as a keyed hash); ``registration_reports`` is the outbox
the worker uses to tell DCS sources that a holder registered.

Revision ID: 7c1d4e9b2a60
Revises: e2a3d2697c0d
Create Date: 2026-10-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c1d4e9b2a60"
down_revision: str | Sequence[str] | None = "e2a3d2697c0d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "pending_invites",
        sa.Column("email_key", sa.String(length=64), nullable=False),
        sa.Column("source_code", sa.String(length=64), nullable=False),
        sa.Column("inviter_name", sa.String(length=200), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pending_invites")),
    )
    op.create_index(
        op.f("ix_pending_invites_email_key"),
        "pending_invites",
        ["email_key"],
        unique=False,
    )
    op.create_table(
        "registration_reports",
        sa.Column("holder_id", sa.Uuid(), nullable=False),
        sa.Column("source_code", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["holder_id"],
            ["holders.id"],
            name=op.f("fk_registration_reports_holder_id_holders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_registration_reports")),
    )
    op.create_index(
        "ix_registration_reports_status_next_attempt",
        "registration_reports",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_registration_reports_status_next_attempt",
        table_name="registration_reports",
    )
    op.drop_table("registration_reports")
    op.drop_index(
        op.f("ix_pending_invites_email_key"), table_name="pending_invites"
    )
    op.drop_table("pending_invites")
