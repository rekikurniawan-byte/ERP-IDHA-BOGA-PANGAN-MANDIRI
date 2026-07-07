"""Add optional COA mapping on bank accounts.

Revision ID: 76a0a1b2c3d4
Revises: 75a0a1b2c3d4
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa


revision = "76a0a1b2c3d4"
down_revision = "75a0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bank_accounts", sa.Column("coa_account_code", sa.String(length=50), nullable=True))
    op.create_index("ix_bank_accounts_coa_account_code", "bank_accounts", ["coa_account_code"])


def downgrade():
    op.drop_index("ix_bank_accounts_coa_account_code", table_name="bank_accounts")
    op.drop_column("bank_accounts", "coa_account_code")
