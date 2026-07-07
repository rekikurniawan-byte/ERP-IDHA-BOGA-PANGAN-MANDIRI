"""PRODUCTION operational expense COA mapping

Revision ID: 66e0a1b2c3d4
Revises: 66d0a1b2c3d4
Create Date: 2026-06-21
"""

from alembic import op
import sqlalchemy as sa


revision = "66e0a1b2c3d4"
down_revision = "66d0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "operational_expenses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("expense_number", sa.String(length=50), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("expense_category", sa.String(length=50), nullable=False),
        sa.Column("account_code", sa.String(length=50), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("vendor_name", sa.String(length=150), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("posting_status", sa.String(length=30), nullable=False),
        sa.Column("cash_bank_transaction_id", sa.Integer(), nullable=True),
        sa.Column("journal_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["cash_bank_transaction_id"], ["cash_bank_transactions.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("expense_number"),
    )
    op.create_index("ix_operational_expenses_branch_id", "operational_expenses", ["branch_id"])
    op.create_index("ix_operational_expenses_expense_number", "operational_expenses", ["expense_number"])
    op.create_index("ix_operational_expenses_expense_date", "operational_expenses", ["expense_date"])
    op.create_index("ix_operational_expenses_expense_category", "operational_expenses", ["expense_category"])
    op.create_index("ix_operational_expenses_account_code", "operational_expenses", ["account_code"])
    op.create_index("ix_operational_expenses_supplier_id", "operational_expenses", ["supplier_id"])
    op.create_index("ix_operational_expenses_posting_status", "operational_expenses", ["posting_status"])


def downgrade():
    op.drop_index("ix_operational_expenses_posting_status", table_name="operational_expenses")
    op.drop_index("ix_operational_expenses_supplier_id", table_name="operational_expenses")
    op.drop_index("ix_operational_expenses_account_code", table_name="operational_expenses")
    op.drop_index("ix_operational_expenses_expense_category", table_name="operational_expenses")
    op.drop_index("ix_operational_expenses_expense_date", table_name="operational_expenses")
    op.drop_index("ix_operational_expenses_expense_number", table_name="operational_expenses")
    op.drop_index("ix_operational_expenses_branch_id", table_name="operational_expenses")
    op.drop_table("operational_expenses")
