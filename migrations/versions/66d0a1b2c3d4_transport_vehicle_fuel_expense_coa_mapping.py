"""PRODUCTION transport and vehicle fuel expense COA mapping

Revision ID: 66d0a1b2c3d4
Revises: 66c0a1b2c3d4
Create Date: 2026-06-21
"""

from alembic import op
import sqlalchemy as sa


revision = "66d0a1b2c3d4"
down_revision = "66c0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "transport_vehicle_expenses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("expense_number", sa.String(length=50), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("expense_type", sa.String(length=50), nullable=False),
        sa.Column("account_code", sa.String(length=50), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("vehicle_label", sa.String(length=150), nullable=True),
        sa.Column("driver_id", sa.Integer(), nullable=True),
        sa.Column("delivery_id", sa.Integer(), nullable=True),
        sa.Column("vendor_name", sa.String(length=150), nullable=True),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cash_bank_transaction_id", sa.Integer(), nullable=True),
        sa.Column("journal_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["cash_bank_transaction_id"], ["cash_bank_transactions.id"]),
        sa.ForeignKeyConstraint(["delivery_id"], ["deliveries.id"]),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("expense_number"),
    )
    op.create_index("ix_transport_vehicle_expenses_branch_id", "transport_vehicle_expenses", ["branch_id"])
    op.create_index("ix_transport_vehicle_expenses_expense_number", "transport_vehicle_expenses", ["expense_number"])
    op.create_index("ix_transport_vehicle_expenses_expense_date", "transport_vehicle_expenses", ["expense_date"])
    op.create_index("ix_transport_vehicle_expenses_expense_type", "transport_vehicle_expenses", ["expense_type"])
    op.create_index("ix_transport_vehicle_expenses_account_code", "transport_vehicle_expenses", ["account_code"])
    op.create_index("ix_transport_vehicle_expenses_driver_id", "transport_vehicle_expenses", ["driver_id"])
    op.create_index("ix_transport_vehicle_expenses_delivery_id", "transport_vehicle_expenses", ["delivery_id"])


def downgrade():
    op.drop_index("ix_transport_vehicle_expenses_delivery_id", table_name="transport_vehicle_expenses")
    op.drop_index("ix_transport_vehicle_expenses_driver_id", table_name="transport_vehicle_expenses")
    op.drop_index("ix_transport_vehicle_expenses_account_code", table_name="transport_vehicle_expenses")
    op.drop_index("ix_transport_vehicle_expenses_expense_type", table_name="transport_vehicle_expenses")
    op.drop_index("ix_transport_vehicle_expenses_expense_date", table_name="transport_vehicle_expenses")
    op.drop_index("ix_transport_vehicle_expenses_expense_number", table_name="transport_vehicle_expenses")
    op.drop_index("ix_transport_vehicle_expenses_branch_id", table_name="transport_vehicle_expenses")
    op.drop_table("transport_vehicle_expenses")
