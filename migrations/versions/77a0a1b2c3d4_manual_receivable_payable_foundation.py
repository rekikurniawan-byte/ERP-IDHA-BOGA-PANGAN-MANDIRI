"""Manual receivable and payable foundation for field transactions.

Revision ID: 77a0a1b2c3d4
Revises: 76a0a1b2c3d4
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa


revision = "77a0a1b2c3d4"
down_revision = "76a0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "manual_receivables",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("receivable_number", sa.String(length=50), nullable=False),
        sa.Column("field_transaction_id", sa.Integer(), nullable=False),
        sa.Column("counterparty_id", sa.Integer(), nullable=True),
        sa.Column("receivable_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("party_name", sa.String(length=150), nullable=False),
        sa.Column("party_company", sa.String(length=150), nullable=True),
        sa.Column("party_phone", sa.String(length=50), nullable=True),
        sa.Column("total_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("paid_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("remaining_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="OPEN"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["counterparty_id"], ["field_counterparties.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["field_transaction_id"], ["field_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("field_transaction_id"),
        sa.UniqueConstraint("receivable_number"),
    )
    op.create_index("ix_manual_receivables_branch_id", "manual_receivables", ["branch_id"])
    op.create_index("ix_manual_receivables_receivable_number", "manual_receivables", ["receivable_number"])
    op.create_index("ix_manual_receivables_field_transaction_id", "manual_receivables", ["field_transaction_id"])
    op.create_index("ix_manual_receivables_counterparty_id", "manual_receivables", ["counterparty_id"])
    op.create_index("ix_manual_receivables_receivable_date", "manual_receivables", ["receivable_date"])
    op.create_index("ix_manual_receivables_due_date", "manual_receivables", ["due_date"])
    op.create_index("ix_manual_receivables_status", "manual_receivables", ["status"])
    op.create_index("ix_manual_receivables_created_by", "manual_receivables", ["created_by"])

    op.create_table(
        "manual_receivable_payments",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("payment_number", sa.String(length=50), nullable=False),
        sa.Column("manual_receivable_id", sa.Integer(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("paid_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["manual_receivable_id"], ["manual_receivables.id"]),
        sa.ForeignKeyConstraint(["paid_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_number"),
    )
    op.create_index("ix_manual_receivable_payments_branch_id", "manual_receivable_payments", ["branch_id"])
    op.create_index("ix_manual_receivable_payments_payment_number", "manual_receivable_payments", ["payment_number"])
    op.create_index("ix_manual_receivable_payments_manual_receivable_id", "manual_receivable_payments", ["manual_receivable_id"])
    op.create_index("ix_manual_receivable_payments_payment_date", "manual_receivable_payments", ["payment_date"])
    op.create_index("ix_manual_receivable_payments_bank_account_id", "manual_receivable_payments", ["bank_account_id"])
    op.create_index("ix_manual_receivable_payments_paid_by", "manual_receivable_payments", ["paid_by"])

    op.create_table(
        "manual_payables",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("payable_number", sa.String(length=50), nullable=False),
        sa.Column("field_transaction_id", sa.Integer(), nullable=False),
        sa.Column("counterparty_id", sa.Integer(), nullable=True),
        sa.Column("payable_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("party_name", sa.String(length=150), nullable=False),
        sa.Column("party_company", sa.String(length=150), nullable=True),
        sa.Column("party_phone", sa.String(length=50), nullable=True),
        sa.Column("total_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("paid_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("remaining_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="OPEN"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["counterparty_id"], ["field_counterparties.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["field_transaction_id"], ["field_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("field_transaction_id"),
        sa.UniqueConstraint("payable_number"),
    )
    op.create_index("ix_manual_payables_branch_id", "manual_payables", ["branch_id"])
    op.create_index("ix_manual_payables_payable_number", "manual_payables", ["payable_number"])
    op.create_index("ix_manual_payables_field_transaction_id", "manual_payables", ["field_transaction_id"])
    op.create_index("ix_manual_payables_counterparty_id", "manual_payables", ["counterparty_id"])
    op.create_index("ix_manual_payables_payable_date", "manual_payables", ["payable_date"])
    op.create_index("ix_manual_payables_due_date", "manual_payables", ["due_date"])
    op.create_index("ix_manual_payables_status", "manual_payables", ["status"])
    op.create_index("ix_manual_payables_created_by", "manual_payables", ["created_by"])

    op.create_table(
        "manual_payable_payments",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("payment_number", sa.String(length=50), nullable=False),
        sa.Column("manual_payable_id", sa.Integer(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("paid_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["manual_payable_id"], ["manual_payables.id"]),
        sa.ForeignKeyConstraint(["paid_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_number"),
    )
    op.create_index("ix_manual_payable_payments_branch_id", "manual_payable_payments", ["branch_id"])
    op.create_index("ix_manual_payable_payments_payment_number", "manual_payable_payments", ["payment_number"])
    op.create_index("ix_manual_payable_payments_manual_payable_id", "manual_payable_payments", ["manual_payable_id"])
    op.create_index("ix_manual_payable_payments_payment_date", "manual_payable_payments", ["payment_date"])
    op.create_index("ix_manual_payable_payments_bank_account_id", "manual_payable_payments", ["bank_account_id"])
    op.create_index("ix_manual_payable_payments_paid_by", "manual_payable_payments", ["paid_by"])


def downgrade():
    op.drop_index("ix_manual_payable_payments_paid_by", table_name="manual_payable_payments")
    op.drop_index("ix_manual_payable_payments_bank_account_id", table_name="manual_payable_payments")
    op.drop_index("ix_manual_payable_payments_payment_date", table_name="manual_payable_payments")
    op.drop_index("ix_manual_payable_payments_manual_payable_id", table_name="manual_payable_payments")
    op.drop_index("ix_manual_payable_payments_payment_number", table_name="manual_payable_payments")
    op.drop_index("ix_manual_payable_payments_branch_id", table_name="manual_payable_payments")
    op.drop_table("manual_payable_payments")

    op.drop_index("ix_manual_payables_created_by", table_name="manual_payables")
    op.drop_index("ix_manual_payables_status", table_name="manual_payables")
    op.drop_index("ix_manual_payables_due_date", table_name="manual_payables")
    op.drop_index("ix_manual_payables_payable_date", table_name="manual_payables")
    op.drop_index("ix_manual_payables_counterparty_id", table_name="manual_payables")
    op.drop_index("ix_manual_payables_field_transaction_id", table_name="manual_payables")
    op.drop_index("ix_manual_payables_payable_number", table_name="manual_payables")
    op.drop_index("ix_manual_payables_branch_id", table_name="manual_payables")
    op.drop_table("manual_payables")

    op.drop_index("ix_manual_receivable_payments_paid_by", table_name="manual_receivable_payments")
    op.drop_index("ix_manual_receivable_payments_bank_account_id", table_name="manual_receivable_payments")
    op.drop_index("ix_manual_receivable_payments_payment_date", table_name="manual_receivable_payments")
    op.drop_index("ix_manual_receivable_payments_manual_receivable_id", table_name="manual_receivable_payments")
    op.drop_index("ix_manual_receivable_payments_payment_number", table_name="manual_receivable_payments")
    op.drop_index("ix_manual_receivable_payments_branch_id", table_name="manual_receivable_payments")
    op.drop_table("manual_receivable_payments")

    op.drop_index("ix_manual_receivables_created_by", table_name="manual_receivables")
    op.drop_index("ix_manual_receivables_status", table_name="manual_receivables")
    op.drop_index("ix_manual_receivables_due_date", table_name="manual_receivables")
    op.drop_index("ix_manual_receivables_receivable_date", table_name="manual_receivables")
    op.drop_index("ix_manual_receivables_counterparty_id", table_name="manual_receivables")
    op.drop_index("ix_manual_receivables_field_transaction_id", table_name="manual_receivables")
    op.drop_index("ix_manual_receivables_receivable_number", table_name="manual_receivables")
    op.drop_index("ix_manual_receivables_branch_id", table_name="manual_receivables")
    op.drop_table("manual_receivables")
