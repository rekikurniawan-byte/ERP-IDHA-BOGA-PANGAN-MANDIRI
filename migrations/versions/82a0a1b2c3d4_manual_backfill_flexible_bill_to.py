"""Allow flexible billed parties for manual backfill batches.

Revision ID: 82a0a1b2c3d4
Revises: 81a0a1b2c3d4
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa


revision = "82a0a1b2c3d4"
down_revision = "81a0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("manual_billing_batches", "mandor_id", existing_type=sa.Integer(), nullable=True)
    op.add_column("manual_billing_batches", sa.Column("bill_to_name_snapshot", sa.String(length=150), nullable=True))
    op.add_column("manual_billing_batches", sa.Column("bill_to_phone_snapshot", sa.String(length=50), nullable=True))
    op.add_column("manual_billing_batches", sa.Column("bill_to_address_snapshot", sa.Text(), nullable=True))
    op.add_column("manual_billing_batches", sa.Column("bill_to_notes", sa.Text(), nullable=True))
    op.create_index("ix_manual_billing_batches_bill_to_name_snapshot", "manual_billing_batches", ["bill_to_name_snapshot"])

    op.execute(
        """
        UPDATE manual_billing_batches
        SET bill_to_name_snapshot = COALESCE(
            bill_to_name_snapshot,
            (SELECT name FROM mandors WHERE mandors.id = manual_billing_batches.mandor_id),
            (SELECT name FROM clients WHERE clients.id = manual_billing_batches.client_id)
        )
        WHERE bill_to_name_snapshot IS NULL
        """
    )


def downgrade():
    op.drop_index("ix_manual_billing_batches_bill_to_name_snapshot", table_name="manual_billing_batches")
    op.drop_column("manual_billing_batches", "bill_to_notes")
    op.drop_column("manual_billing_batches", "bill_to_address_snapshot")
    op.drop_column("manual_billing_batches", "bill_to_phone_snapshot")
    op.drop_column("manual_billing_batches", "bill_to_name_snapshot")
    op.alter_column("manual_billing_batches", "mandor_id", existing_type=sa.Integer(), nullable=False)
