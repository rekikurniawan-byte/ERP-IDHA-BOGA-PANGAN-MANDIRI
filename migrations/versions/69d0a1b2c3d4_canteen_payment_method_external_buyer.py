"""PRODUCTION canteen payment method and external buyer foundation

Revision ID: 69d0a1b2c3d4
Revises: 66g0a1b2c3d4
Create Date: 2026-06-24
"""

from alembic import op
import sqlalchemy as sa


revision = "69d0a1b2c3d4"
down_revision = "66g0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("canteen_sales") as batch_op:
        batch_op.add_column(sa.Column("payment_method", sa.String(length=30), nullable=False, server_default="CASH"))
        batch_op.add_column(sa.Column("buyer_type", sa.String(length=40), nullable=False, server_default="GENERAL_BUYER"))
        batch_op.add_column(sa.Column("buyer_name", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("buyer_company", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("buyer_phone", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("payment_reference", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("cash_bank_account_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("is_external_debt", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_foreign_key("fk_canteen_sales_cash_bank_account", "bank_accounts", ["cash_bank_account_id"], ["id"])

    op.execute("UPDATE canteen_sales SET payment_method = CASE WHEN sale_type = 'DEBT' THEN 'DEBT' ELSE 'CASH' END WHERE payment_method IS NULL OR payment_method = ''")
    op.execute("UPDATE canteen_sales SET buyer_type = CASE WHEN sale_type = 'DEBT' THEN 'REGISTERED_WORKER' ELSE 'GENERAL_BUYER' END WHERE buyer_type IS NULL OR buyer_type = ''")
    op.create_index("ix_canteen_sales_payment_method", "canteen_sales", ["payment_method"])
    op.create_index("ix_canteen_sales_buyer_type", "canteen_sales", ["buyer_type"])
    op.create_index("ix_canteen_sales_is_external_debt", "canteen_sales", ["is_external_debt"])

    with op.batch_alter_table("debt_payments") as batch_op:
        batch_op.add_column(sa.Column("payment_method", sa.String(length=30), nullable=False, server_default="CASH"))
        batch_op.add_column(sa.Column("cash_bank_account_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("payment_reference", sa.String(length=120), nullable=True))
        batch_op.create_foreign_key("fk_debt_payments_cash_bank_account", "bank_accounts", ["cash_bank_account_id"], ["id"])

    op.create_index("ix_debt_payments_payment_method", "debt_payments", ["payment_method"])

    op.create_table(
        "canteen_external_receivables",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("sale_id", sa.Integer(), nullable=False),
        sa.Column("buyer_name", sa.String(length=150), nullable=False),
        sa.Column("buyer_company", sa.String(length=150), nullable=True),
        sa.Column("buyer_phone", sa.String(length=50), nullable=True),
        sa.Column("receivable_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("paid_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("remaining_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="UNPAID"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["sale_id"], ["canteen_sales.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sale_id", name="uq_canteen_external_receivable_sale"),
    )
    op.create_index("ix_canteen_external_receivables_status", "canteen_external_receivables", ["status"])

    op.create_table(
        "canteen_external_receivable_payments",
        sa.Column("receivable_id", sa.Integer(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("payment_method", sa.String(length=30), nullable=False, server_default="CASH"),
        sa.Column("cash_bank_account_id", sa.Integer(), nullable=True),
        sa.Column("payment_reference", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["receivable_id"], ["canteen_external_receivables.id"]),
        sa.ForeignKeyConstraint(["cash_bank_account_id"], ["bank_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_canteen_external_receivable_payments_payment_date", "canteen_external_receivable_payments", ["payment_date"])
    op.create_index("ix_canteen_external_receivable_payments_payment_method", "canteen_external_receivable_payments", ["payment_method"])


def downgrade():
    op.drop_index("ix_canteen_external_receivable_payments_payment_method", table_name="canteen_external_receivable_payments")
    op.drop_index("ix_canteen_external_receivable_payments_payment_date", table_name="canteen_external_receivable_payments")
    op.drop_table("canteen_external_receivable_payments")

    op.drop_index("ix_canteen_external_receivables_status", table_name="canteen_external_receivables")
    op.drop_table("canteen_external_receivables")

    op.drop_index("ix_debt_payments_payment_method", table_name="debt_payments")
    with op.batch_alter_table("debt_payments") as batch_op:
        batch_op.drop_constraint("fk_debt_payments_cash_bank_account", type_="foreignkey")
        batch_op.drop_column("payment_reference")
        batch_op.drop_column("cash_bank_account_id")
        batch_op.drop_column("payment_method")

    op.drop_index("ix_canteen_sales_is_external_debt", table_name="canteen_sales")
    op.drop_index("ix_canteen_sales_buyer_type", table_name="canteen_sales")
    op.drop_index("ix_canteen_sales_payment_method", table_name="canteen_sales")
    with op.batch_alter_table("canteen_sales") as batch_op:
        batch_op.drop_constraint("fk_canteen_sales_cash_bank_account", type_="foreignkey")
        batch_op.drop_column("is_external_debt")
        batch_op.drop_column("cash_bank_account_id")
        batch_op.drop_column("payment_reference")
        batch_op.drop_column("buyer_phone")
        batch_op.drop_column("buyer_company")
        batch_op.drop_column("buyer_name")
        batch_op.drop_column("buyer_type")
        batch_op.drop_column("payment_method")
