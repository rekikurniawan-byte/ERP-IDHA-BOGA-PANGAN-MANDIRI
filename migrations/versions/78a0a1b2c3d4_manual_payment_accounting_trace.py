"""Add accounting trace columns for manual receivable/payable payments.

Revision ID: 78a0a1b2c3d4
Revises: 77a0a1b2c3d4
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa


revision = "78a0a1b2c3d4"
down_revision = "77a0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "manual_receivable_payments",
        sa.Column("cash_bank_transaction_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "manual_receivable_payments",
        sa.Column("journal_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_manual_receivable_payments_cash_bank_transaction_id",
        "manual_receivable_payments",
        "cash_bank_transactions",
        ["cash_bank_transaction_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_manual_receivable_payments_journal_id",
        "manual_receivable_payments",
        "journals",
        ["journal_id"],
        ["id"],
    )
    op.create_index(
        "ix_manual_receivable_payments_cash_bank_transaction_id",
        "manual_receivable_payments",
        ["cash_bank_transaction_id"],
    )
    op.create_index(
        "ix_manual_receivable_payments_journal_id",
        "manual_receivable_payments",
        ["journal_id"],
    )

    op.add_column(
        "manual_payable_payments",
        sa.Column("cash_bank_transaction_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "manual_payable_payments",
        sa.Column("journal_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_manual_payable_payments_cash_bank_transaction_id",
        "manual_payable_payments",
        "cash_bank_transactions",
        ["cash_bank_transaction_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_manual_payable_payments_journal_id",
        "manual_payable_payments",
        "journals",
        ["journal_id"],
        ["id"],
    )
    op.create_index(
        "ix_manual_payable_payments_cash_bank_transaction_id",
        "manual_payable_payments",
        ["cash_bank_transaction_id"],
    )
    op.create_index(
        "ix_manual_payable_payments_journal_id",
        "manual_payable_payments",
        ["journal_id"],
    )


def downgrade():
    op.drop_index("ix_manual_payable_payments_journal_id", table_name="manual_payable_payments")
    op.drop_index("ix_manual_payable_payments_cash_bank_transaction_id", table_name="manual_payable_payments")
    op.drop_constraint(
        "fk_manual_payable_payments_journal_id",
        "manual_payable_payments",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_manual_payable_payments_cash_bank_transaction_id",
        "manual_payable_payments",
        type_="foreignkey",
    )
    op.drop_column("manual_payable_payments", "journal_id")
    op.drop_column("manual_payable_payments", "cash_bank_transaction_id")

    op.drop_index("ix_manual_receivable_payments_journal_id", table_name="manual_receivable_payments")
    op.drop_index("ix_manual_receivable_payments_cash_bank_transaction_id", table_name="manual_receivable_payments")
    op.drop_constraint(
        "fk_manual_receivable_payments_journal_id",
        "manual_receivable_payments",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_manual_receivable_payments_cash_bank_transaction_id",
        "manual_receivable_payments",
        type_="foreignkey",
    )
    op.drop_column("manual_receivable_payments", "journal_id")
    op.drop_column("manual_receivable_payments", "cash_bank_transaction_id")
