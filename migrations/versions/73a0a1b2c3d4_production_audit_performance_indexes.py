"""Production audit: add missing performance indexes.

Revision ID: 73a0a1b2c3d4
Revises: 72a0a1b2c3d4
Create Date: 2026-06-29

Indexes added for:
- journal_details.journal_id (heavily used in joins/aggregates)
- journal_details.account_id (used in COA reports)
- cash_bank_transactions (reference_type, reference_id) composite (idempotency checks)
"""
from alembic import op


revision = "73a0a1b2c3d4"
down_revision = "72a0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_journal_details_journal_id",
        "journal_details",
        ["journal_id"],
        unique=False,
    )
    op.create_index(
        "ix_journal_details_account_id",
        "journal_details",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_cash_bank_transactions_reference",
        "cash_bank_transactions",
        ["reference_type", "reference_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_cash_bank_transactions_reference", table_name="cash_bank_transactions")
    op.drop_index("ix_journal_details_account_id", table_name="journal_details")
    op.drop_index("ix_journal_details_journal_id", table_name="journal_details")
