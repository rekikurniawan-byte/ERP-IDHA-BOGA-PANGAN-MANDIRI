"""Align items selling price column for clean PostgreSQL upgrades.

Revision ID: 89a0a1b2c3d4
Revises: 88a0a1b2c3d4
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa


revision = "89a0a1b2c3d4"
down_revision = "88a0a1b2c3d4"
branch_labels = None
depends_on = None


def _column_exists(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    if _column_exists("items", "selling_price"):
        return

    op.add_column(
        "items",
        sa.Column("selling_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )
    op.alter_column("items", "selling_price", server_default=None)


def downgrade():
    # Non-destructive by design. Some existing databases already had this
    # column before this alignment migration, so dropping it here could remove
    # real production/staging data.
    pass
