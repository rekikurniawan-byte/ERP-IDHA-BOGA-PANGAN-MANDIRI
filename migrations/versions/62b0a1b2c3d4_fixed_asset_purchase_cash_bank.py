"""fixed asset purchase cash bank foundation

Revision ID: 62b0a1b2c3d4
Revises: 60f0a1b2c3d4
Create Date: 2026-06-20 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "62b0a1b2c3d4"
down_revision = "60f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fixed_asset_purchases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("purchase_number", sa.String(length=50), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("fixed_asset_id", sa.Integer(), nullable=False),
        sa.Column("asset_account_code", sa.String(length=50), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("vendor_name", sa.String(length=150), nullable=True),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cash_bank_transaction_id", sa.Integer(), nullable=True),
        sa.Column("journal_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["cash_bank_transaction_id"], ["cash_bank_transactions.id"]),
        sa.ForeignKeyConstraint(["fixed_asset_id"], ["fixed_assets.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fixed_asset_id", name="uq_fixed_asset_purchases_asset_once"),
        sa.UniqueConstraint("purchase_number"),
    )
    op.create_index(op.f("ix_fixed_asset_purchases_purchase_number"), "fixed_asset_purchases", ["purchase_number"], unique=False)
    op.create_index(op.f("ix_fixed_asset_purchases_purchase_date"), "fixed_asset_purchases", ["purchase_date"], unique=False)
    op.create_index(op.f("ix_fixed_asset_purchases_fixed_asset_id"), "fixed_asset_purchases", ["fixed_asset_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_fixed_asset_purchases_fixed_asset_id"), table_name="fixed_asset_purchases")
    op.drop_index(op.f("ix_fixed_asset_purchases_purchase_date"), table_name="fixed_asset_purchases")
    op.drop_index(op.f("ix_fixed_asset_purchases_purchase_number"), table_name="fixed_asset_purchases")
    op.drop_table("fixed_asset_purchases")
