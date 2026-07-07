"""PRODUCTION asset vehicle installment foundation

Revision ID: 71f0a1b2c3d4
Revises: 69i0a1b2c3d4
Create Date: 2026-06-24
"""

from alembic import op
import sqlalchemy as sa


revision = "71f0a1b2c3d4"
down_revision = "69i0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "asset_financing_contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("contract_number", sa.String(length=50), nullable=False),
        sa.Column("contract_date", sa.Date(), nullable=False),
        sa.Column("fixed_asset_id", sa.Integer(), nullable=False),
        sa.Column("asset_account_code", sa.String(length=50), nullable=False),
        sa.Column("liability_account_code", sa.String(length=50), nullable=False),
        sa.Column("interest_expense_account_code", sa.String(length=50), nullable=False),
        sa.Column("admin_expense_account_code", sa.String(length=50), nullable=False),
        sa.Column("vendor_name", sa.String(length=150), nullable=True),
        sa.Column("financing_provider", sa.String(length=150), nullable=True),
        sa.Column("principal_amount", sa.Float(), nullable=False),
        sa.Column("total_interest_amount", sa.Float(), nullable=False),
        sa.Column("total_admin_amount", sa.Float(), nullable=False),
        sa.Column("total_contract_amount", sa.Float(), nullable=False),
        sa.Column("installment_count", sa.Integer(), nullable=False),
        sa.Column("installment_frequency", sa.String(length=30), nullable=False),
        sa.Column("first_due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("acquisition_journal_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["acquisition_journal_id"], ["journals.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["fixed_asset_id"], ["fixed_assets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_number"),
    )
    op.create_index("ix_asset_financing_contracts_branch_id", "asset_financing_contracts", ["branch_id"])
    op.create_index("ix_asset_financing_contracts_contract_number", "asset_financing_contracts", ["contract_number"])
    op.create_index("ix_asset_financing_contracts_contract_date", "asset_financing_contracts", ["contract_date"])
    op.create_index("ix_asset_financing_contracts_fixed_asset_id", "asset_financing_contracts", ["fixed_asset_id"])
    op.create_index("ix_asset_financing_contracts_first_due_date", "asset_financing_contracts", ["first_due_date"])
    op.create_index("ix_asset_financing_contracts_status", "asset_financing_contracts", ["status"])

    op.create_table(
        "asset_installment_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("installment_no", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("principal_amount", sa.Float(), nullable=False),
        sa.Column("interest_amount", sa.Float(), nullable=False),
        sa.Column("admin_amount", sa.Float(), nullable=False),
        sa.Column("total_amount", sa.Float(), nullable=False),
        sa.Column("paid_amount", sa.Float(), nullable=False),
        sa.Column("remaining_amount", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["contract_id"], ["asset_financing_contracts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_id", "installment_no", name="uq_asset_installment_contract_no"),
    )
    op.create_index("ix_asset_installment_schedules_branch_id", "asset_installment_schedules", ["branch_id"])
    op.create_index("ix_asset_installment_schedules_contract_id", "asset_installment_schedules", ["contract_id"])
    op.create_index("ix_asset_installment_schedules_due_date", "asset_installment_schedules", ["due_date"])
    op.create_index("ix_asset_installment_schedules_status", "asset_installment_schedules", ["status"])

    op.create_table(
        "asset_installment_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("payment_number", sa.String(length=50), nullable=False),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("schedule_id", sa.Integer(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("principal_paid", sa.Float(), nullable=False),
        sa.Column("interest_paid", sa.Float(), nullable=False),
        sa.Column("admin_paid", sa.Float(), nullable=False),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cash_bank_transaction_id", sa.Integer(), nullable=True),
        sa.Column("journal_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["cash_bank_transaction_id"], ["cash_bank_transactions.id"]),
        sa.ForeignKeyConstraint(["contract_id"], ["asset_financing_contracts.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.ForeignKeyConstraint(["schedule_id"], ["asset_installment_schedules.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_number"),
    )
    op.create_index("ix_asset_installment_payments_branch_id", "asset_installment_payments", ["branch_id"])
    op.create_index("ix_asset_installment_payments_payment_number", "asset_installment_payments", ["payment_number"])
    op.create_index("ix_asset_installment_payments_contract_id", "asset_installment_payments", ["contract_id"])
    op.create_index("ix_asset_installment_payments_schedule_id", "asset_installment_payments", ["schedule_id"])
    op.create_index("ix_asset_installment_payments_payment_date", "asset_installment_payments", ["payment_date"])


def downgrade():
    op.drop_index("ix_asset_installment_payments_payment_date", table_name="asset_installment_payments")
    op.drop_index("ix_asset_installment_payments_schedule_id", table_name="asset_installment_payments")
    op.drop_index("ix_asset_installment_payments_contract_id", table_name="asset_installment_payments")
    op.drop_index("ix_asset_installment_payments_payment_number", table_name="asset_installment_payments")
    op.drop_index("ix_asset_installment_payments_branch_id", table_name="asset_installment_payments")
    op.drop_table("asset_installment_payments")

    op.drop_index("ix_asset_installment_schedules_status", table_name="asset_installment_schedules")
    op.drop_index("ix_asset_installment_schedules_due_date", table_name="asset_installment_schedules")
    op.drop_index("ix_asset_installment_schedules_contract_id", table_name="asset_installment_schedules")
    op.drop_index("ix_asset_installment_schedules_branch_id", table_name="asset_installment_schedules")
    op.drop_table("asset_installment_schedules")

    op.drop_index("ix_asset_financing_contracts_status", table_name="asset_financing_contracts")
    op.drop_index("ix_asset_financing_contracts_first_due_date", table_name="asset_financing_contracts")
    op.drop_index("ix_asset_financing_contracts_fixed_asset_id", table_name="asset_financing_contracts")
    op.drop_index("ix_asset_financing_contracts_contract_date", table_name="asset_financing_contracts")
    op.drop_index("ix_asset_financing_contracts_contract_number", table_name="asset_financing_contracts")
    op.drop_index("ix_asset_financing_contracts_branch_id", table_name="asset_financing_contracts")
    op.drop_table("asset_financing_contracts")
