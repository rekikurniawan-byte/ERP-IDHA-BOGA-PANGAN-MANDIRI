"""Add unique constraint on invoice source_type + source_order_id + mandor_id.

Prevents duplicate invoices for the same order+mandor combination.

Revision ID: 74a0a1b2c3d4
Revises: 73a0a1b2c3d4
Create Date: 2026-06-30
"""
from alembic import op


revision = "74a0a1b2c3d4"
down_revision = "73a0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    # Partial unique constraint: only applies when source_type and source_order_id are NOT NULL
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_invoices_source_order_mandor
        ON invoices (source_type, source_order_id, mandor_id)
        WHERE source_type IS NOT NULL AND source_order_id IS NOT NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_invoices_source_order_mandor")
