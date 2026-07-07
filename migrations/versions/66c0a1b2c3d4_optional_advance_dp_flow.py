"""PRODUCTION optional advance / DP flow

Revision ID: 66c0a1b2c3d4
Revises: 63f0a1b2c3d4
Create Date: 2026-06-21
"""

from alembic import op
import sqlalchemy as sa


revision = "66c0a1b2c3d4"
down_revision = "63f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "advance_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("advance_number", sa.String(length=50), nullable=False),
        sa.Column("advance_date", sa.Date(), nullable=False),
        sa.Column("advance_type", sa.String(length=50), nullable=False),
        sa.Column("party_type", sa.String(length=30), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("mandor_id", sa.Integer(), nullable=True),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("settled_amount", sa.Float(), nullable=False),
        sa.Column("remaining_amount", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cash_bank_transaction_id", sa.Integer(), nullable=True),
        sa.Column("journal_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["cash_bank_transaction_id"], ["cash_bank_transactions.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.ForeignKeyConstraint(["mandor_id"], ["mandors.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("advance_number"),
    )
    op.create_index("ix_advance_transactions_branch_id", "advance_transactions", ["branch_id"])
    op.create_index("ix_advance_transactions_advance_number", "advance_transactions", ["advance_number"])
    op.create_index("ix_advance_transactions_advance_date", "advance_transactions", ["advance_date"])
    op.create_index("ix_advance_transactions_advance_type", "advance_transactions", ["advance_type"])
    op.create_index("ix_advance_transactions_party_type", "advance_transactions", ["party_type"])
    op.create_index("ix_advance_transactions_client_id", "advance_transactions", ["client_id"])
    op.create_index("ix_advance_transactions_supplier_id", "advance_transactions", ["supplier_id"])
    op.create_index("ix_advance_transactions_mandor_id", "advance_transactions", ["mandor_id"])
    op.create_index("ix_advance_transactions_status", "advance_transactions", ["status"])

    op.create_table(
        "advance_settlements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("settlement_number", sa.String(length=50), nullable=False),
        sa.Column("advance_id", sa.Integer(), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column("settlement_type", sa.String(length=50), nullable=False),
        sa.Column("reference_type", sa.String(length=50), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("journal_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["advance_id"], ["advance_transactions.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("settlement_number"),
    )
    op.create_index("ix_advance_settlements_branch_id", "advance_settlements", ["branch_id"])
    op.create_index("ix_advance_settlements_settlement_number", "advance_settlements", ["settlement_number"])
    op.create_index("ix_advance_settlements_advance_id", "advance_settlements", ["advance_id"])
    op.create_index("ix_advance_settlements_settlement_date", "advance_settlements", ["settlement_date"])
    op.create_index("ix_advance_settlements_settlement_type", "advance_settlements", ["settlement_type"])
    op.create_index("ix_advance_settlements_reference_type", "advance_settlements", ["reference_type"])
    op.create_index("ix_advance_settlements_reference_id", "advance_settlements", ["reference_id"])


def downgrade():
    op.drop_index("ix_advance_settlements_reference_id", table_name="advance_settlements")
    op.drop_index("ix_advance_settlements_reference_type", table_name="advance_settlements")
    op.drop_index("ix_advance_settlements_settlement_type", table_name="advance_settlements")
    op.drop_index("ix_advance_settlements_settlement_date", table_name="advance_settlements")
    op.drop_index("ix_advance_settlements_advance_id", table_name="advance_settlements")
    op.drop_index("ix_advance_settlements_settlement_number", table_name="advance_settlements")
    op.drop_index("ix_advance_settlements_branch_id", table_name="advance_settlements")
    op.drop_table("advance_settlements")

    op.drop_index("ix_advance_transactions_status", table_name="advance_transactions")
    op.drop_index("ix_advance_transactions_mandor_id", table_name="advance_transactions")
    op.drop_index("ix_advance_transactions_supplier_id", table_name="advance_transactions")
    op.drop_index("ix_advance_transactions_client_id", table_name="advance_transactions")
    op.drop_index("ix_advance_transactions_party_type", table_name="advance_transactions")
    op.drop_index("ix_advance_transactions_advance_type", table_name="advance_transactions")
    op.drop_index("ix_advance_transactions_advance_date", table_name="advance_transactions")
    op.drop_index("ix_advance_transactions_advance_number", table_name="advance_transactions")
    op.drop_index("ix_advance_transactions_branch_id", table_name="advance_transactions")
    op.drop_table("advance_transactions")
