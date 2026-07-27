"""Add stock opening balance foundation.

Revision ID: 86a0a1b2c3d4
Revises: 85a0a1b2c3d4
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa


revision = "86a0a1b2c3d4"
down_revision = "85a0a1b2c3d4"
branch_labels = None
depends_on = None


MONEY_COLUMNS = {}
QUANTITY_COLUMNS = {
    "stock_opening_balances": ["qty"],
}
RATIO_COLUMNS = {}
VERSIONED_TABLES = ("stock_opening_balances",)


def upgrade():
    op.create_table(
        "stock_opening_balances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("opening_date", sa.Date(), nullable=False),
        sa.Column("qty", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "item_id", name="uq_stock_opening_balance_branch_item"),
    )
    op.create_index(op.f("ix_stock_opening_balances_branch_id"), "stock_opening_balances", ["branch_id"], unique=False)
    op.create_index(op.f("ix_stock_opening_balances_item_id"), "stock_opening_balances", ["item_id"], unique=False)
    op.create_index(op.f("ix_stock_opening_balances_opening_date"), "stock_opening_balances", ["opening_date"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_stock_opening_balances_opening_date"), table_name="stock_opening_balances")
    op.drop_index(op.f("ix_stock_opening_balances_item_id"), table_name="stock_opening_balances")
    op.drop_index(op.f("ix_stock_opening_balances_branch_id"), table_name="stock_opening_balances")
    op.drop_table("stock_opening_balances")
