"""cash bank opening transfer reconciliation

Revision ID: 57a0f1a2b3c4
Revises: 56l0e1f2a3b4
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa


revision = "57a0f1a2b3c4"
down_revision = "56l0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cash_bank_opening_balances",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("account_key", sa.String(length=80), nullable=False),
        sa.Column("opening_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("ledger_transaction_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["ledger_transaction_id"], ["cash_bank_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "account_key", name="uq_cash_bank_opening_balance_account"),
    )
    op.create_index(op.f("ix_cash_bank_opening_balances_account_key"), "cash_bank_opening_balances", ["account_key"], unique=False)
    op.create_index(op.f("ix_cash_bank_opening_balances_opening_date"), "cash_bank_opening_balances", ["opening_date"], unique=False)

    op.create_table(
        "cash_bank_transfers",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("transfer_number", sa.String(length=50), nullable=False),
        sa.Column("transfer_date", sa.Date(), nullable=False),
        sa.Column("from_account_type", sa.String(length=30), nullable=False),
        sa.Column("from_bank_account_id", sa.Integer(), nullable=True),
        sa.Column("to_account_type", sa.String(length=30), nullable=False),
        sa.Column("to_bank_account_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["from_bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["to_bank_account_id"], ["bank_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transfer_number"),
    )
    op.create_index(op.f("ix_cash_bank_transfers_transfer_date"), "cash_bank_transfers", ["transfer_date"], unique=False)

    op.create_table(
        "cash_bank_adjustments",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("adjustment_number", sa.String(length=50), nullable=False),
        sa.Column("adjustment_date", sa.Date(), nullable=False),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("account_key", sa.String(length=80), nullable=False),
        sa.Column("adjustment_type", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=150), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("ledger_transaction_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["ledger_transaction_id"], ["cash_bank_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("adjustment_number"),
    )
    op.create_index(op.f("ix_cash_bank_adjustments_account_key"), "cash_bank_adjustments", ["account_key"], unique=False)
    op.create_index(op.f("ix_cash_bank_adjustments_adjustment_date"), "cash_bank_adjustments", ["adjustment_date"], unique=False)

    with op.batch_alter_table("cash_bank_transactions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("transfer_group_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("is_reconciled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("reconciled_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("reconciled_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("reconciliation_note", sa.Text(), nullable=True))
        batch_op.create_foreign_key("fk_cash_bank_transactions_transfer_group", "cash_bank_transfers", ["transfer_group_id"], ["id"])
        batch_op.create_index(op.f("ix_cash_bank_transactions_transfer_group_id"), ["transfer_group_id"], unique=False)
        batch_op.create_index(op.f("ix_cash_bank_transactions_is_reconciled"), ["is_reconciled"], unique=False)


def downgrade():
    with op.batch_alter_table("cash_bank_transactions", schema=None) as batch_op:
        batch_op.drop_index(op.f("ix_cash_bank_transactions_is_reconciled"))
        batch_op.drop_index(op.f("ix_cash_bank_transactions_transfer_group_id"))
        batch_op.drop_constraint("fk_cash_bank_transactions_transfer_group", type_="foreignkey")
        batch_op.drop_column("reconciliation_note")
        batch_op.drop_column("reconciled_by")
        batch_op.drop_column("reconciled_at")
        batch_op.drop_column("is_reconciled")
        batch_op.drop_column("transfer_group_id")

    op.drop_index(op.f("ix_cash_bank_adjustments_adjustment_date"), table_name="cash_bank_adjustments")
    op.drop_index(op.f("ix_cash_bank_adjustments_account_key"), table_name="cash_bank_adjustments")
    op.drop_table("cash_bank_adjustments")

    op.drop_index(op.f("ix_cash_bank_transfers_transfer_date"), table_name="cash_bank_transfers")
    op.drop_table("cash_bank_transfers")

    op.drop_index(op.f("ix_cash_bank_opening_balances_opening_date"), table_name="cash_bank_opening_balances")
    op.drop_index(op.f("ix_cash_bank_opening_balances_account_key"), table_name="cash_bank_opening_balances")
    op.drop_table("cash_bank_opening_balances")
