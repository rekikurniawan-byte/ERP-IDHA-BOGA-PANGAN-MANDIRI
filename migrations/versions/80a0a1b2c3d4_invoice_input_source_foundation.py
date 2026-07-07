"""Add input source marker for realtime versus manual backfill billing flows.

Revision ID: 80a0a1b2c3d4
Revises: 79a0a1b2c3d4
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa


revision = "80a0a1b2c3d4"
down_revision = "79a0a1b2c3d4"
branch_labels = None
depends_on = None


_TABLES = (
    "invoices",
    "invoice_items",
    "manual_billing_batches",
    "manual_billing_batch_items",
)


def upgrade():
    for table_name in _TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "input_source",
                sa.String(length=30),
                nullable=False,
                server_default="REALTIME",
            ),
        )
        op.create_index(
            f"ix_{table_name}_input_source",
            table_name,
            ["input_source"],
        )

    # Existing invoice/tagihan data came from the live system flow. Future
    # manual-book backfill will explicitly write MANUAL_BACKFILL.
    for table_name in _TABLES:
        op.execute(f"UPDATE {table_name} SET input_source = 'REALTIME' WHERE input_source IS NULL")


def downgrade():
    for table_name in reversed(_TABLES):
        op.drop_index(f"ix_{table_name}_input_source", table_name=table_name)
        op.drop_column(table_name, "input_source")
