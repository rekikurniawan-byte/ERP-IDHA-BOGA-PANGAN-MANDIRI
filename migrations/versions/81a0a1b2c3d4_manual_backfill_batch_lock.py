"""Add lock audit fields for manual-book backfill billing batches.

Revision ID: 81a0a1b2c3d4
Revises: 80a0a1b2c3d4
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa


revision = "81a0a1b2c3d4"
down_revision = "80a0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("manual_billing_batches", sa.Column("locked_at", sa.DateTime(), nullable=True))
    op.add_column("manual_billing_batches", sa.Column("locked_by", sa.Integer(), nullable=True))
    op.create_index("ix_manual_billing_batches_locked_at", "manual_billing_batches", ["locked_at"])


def downgrade():
    op.drop_index("ix_manual_billing_batches_locked_at", table_name="manual_billing_batches")
    op.drop_column("manual_billing_batches", "locked_by")
    op.drop_column("manual_billing_batches", "locked_at")
