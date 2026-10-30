"""Wallet compatible ids and account deletion.

Adds the integer ids the wallet app expects (``holders.numeric_id`` and
the ``credential_refs`` table), soft deletion of holders, OTP use
tracking, and push token device details. Existing holders get a random
``numeric_id`` before the column becomes required.

Revision ID: e2a3d2697c0d
Revises: af504411783d
Create Date: 2026-10-22 18:48:14.590725

"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2a3d2697c0d"
down_revision: str | Sequence[str] | None = "af504411783d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same range as app.core.models.generate_public_id: below 2**53, so
# JavaScript clients can hold the value. Not imported, so the migration
# keeps working if the app code changes.
_PUBLIC_ID_UPPER_BOUND = 2**52


def _backfill_holder_numeric_ids() -> None:
    connection = op.get_bind()
    holders = sa.table(
        "holders", sa.column("id", sa.Uuid()), sa.column("numeric_id")
    )
    holder_ids = connection.execute(sa.select(holders.c.id)).scalars().all()
    if not holder_ids:
        return
    numeric_ids: set[int] = set()
    while len(numeric_ids) < len(holder_ids):
        numeric_ids.add(secrets.randbelow(_PUBLIC_ID_UPPER_BOUND - 1) + 1)
    # One executemany for every row.
    connection.execute(
        holders.update()
        .where(holders.c.id == sa.bindparam("holder_id"))
        .values(numeric_id=sa.bindparam("new_numeric_id")),
        [
            {"holder_id": holder_id, "new_numeric_id": numeric_id}
            for holder_id, numeric_id in zip(
                holder_ids, numeric_ids, strict=True
            )
        ],
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "credential_refs",
        sa.Column("numeric_id", sa.BigInteger(), nullable=False),
        sa.Column("holder_id", sa.Uuid(), nullable=False),
        sa.Column("source_code", sa.String(length=64), nullable=False),
        sa.Column("credential_id", sa.String(length=128), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["holder_id"],
            ["holders.id"],
            name=op.f("fk_credential_refs_holder_id_holders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credential_refs")),
        sa.UniqueConstraint(
            "holder_id",
            "source_code",
            "credential_id",
            name=op.f("uq_credential_refs_holder_id"),
        ),
        sa.UniqueConstraint(
            "numeric_id", name=op.f("uq_credential_refs_numeric_id")
        ),
    )
    op.create_index(
        op.f("ix_credential_refs_holder_id"),
        "credential_refs",
        ["holder_id"],
        unique=False,
    )
    op.add_column(
        "email_otps", sa.Column("used_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "holders", sa.Column("numeric_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "holders", sa.Column("deleted_at", sa.DateTime(), nullable=True)
    )
    _backfill_holder_numeric_ids()
    # batch_alter_table recreates the table on SQLite, which cannot alter
    # a column in place; on MySQL it issues plain ALTER statements.
    with op.batch_alter_table("holders") as batch_op:
        batch_op.alter_column(
            "numeric_id", existing_type=sa.BigInteger(), nullable=False
        )
        batch_op.create_unique_constraint(
            op.f("uq_holders_numeric_id"), ["numeric_id"]
        )
    op.add_column(
        "push_tokens",
        sa.Column("device_label", sa.String(length=150), nullable=True),
    )
    op.add_column(
        "push_tokens",
        sa.Column("app_version", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("push_tokens", "app_version")
    op.drop_column("push_tokens", "device_label")
    with op.batch_alter_table("holders") as batch_op:
        batch_op.drop_constraint(op.f("uq_holders_numeric_id"), type_="unique")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("numeric_id")
    op.drop_column("email_otps", "used_at")
    op.drop_index(
        op.f("ix_credential_refs_holder_id"), table_name="credential_refs"
    )
    op.drop_table("credential_refs")
