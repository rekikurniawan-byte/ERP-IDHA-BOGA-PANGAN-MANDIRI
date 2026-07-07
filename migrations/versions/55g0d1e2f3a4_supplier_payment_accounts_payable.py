"""supplier payment accounts payable

Revision ID: 55g0d1e2f3a4
Revises: 55f0c1d2e3f4
Create Date: 2026-06-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "55g0d1e2f3a4"
down_revision = "55f0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "supplier_payments",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("payment_number", sa.String(length=50), nullable=False),
        sa.Column("supplier_bill_id", sa.Integer(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("paid_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["supplier_bill_id"], ["supplier_bills.id"]),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_number"),
    )
    op.create_index(op.f("ix_supplier_payments_payment_date"), "supplier_payments", ["payment_date"], unique=False)
    op.create_index(op.f("ix_supplier_payments_supplier_bill_id"), "supplier_payments", ["supplier_bill_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_supplier_payments_supplier_bill_id"), table_name="supplier_payments")
    op.drop_index(op.f("ix_supplier_payments_payment_date"), table_name="supplier_payments")
    op.drop_table("supplier_payments")
