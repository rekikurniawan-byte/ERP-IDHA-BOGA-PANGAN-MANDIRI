"""Kasbon karyawan: dicairkan dari kas/bank, dicicil dari gaji (piutang 1005).

Revision ID: o3f4a5b6c7d8
Revises: n2c3d4e5f6a7
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa


revision = "o3f4a5b6c7d8"
down_revision = "n2c3d4e5f6a7"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {"employee_charges": ("installment_amount",)}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}
VERSIONED_TABLES = ()


def upgrade():
    with op.batch_alter_table("employee_charges") as batch:
        batch.drop_constraint("ck_employee_charges_type", type_="check")
        batch.create_check_constraint("ck_employee_charges_type", "charge_type IN ('DENDA', 'GANTI_RUGI', 'KASBON')")
        batch.add_column(sa.Column("installment_amount", sa.Numeric(18, 2), nullable=True))
        batch.add_column(sa.Column("cash_account_type", sa.String(length=10), nullable=True))
        batch.add_column(sa.Column("bank_account_id", sa.Integer(), sa.ForeignKey("bank_accounts.id"), nullable=True))
        batch.add_column(sa.Column("cash_bank_transaction_id", sa.Integer(), sa.ForeignKey("cash_bank_transactions.id"), nullable=True))
        batch.add_column(sa.Column("signature_attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=True))
        batch.add_column(sa.Column("disbursed_on", sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table("employee_charges") as batch:
        for column in ("disbursed_on", "signature_attachment_id", "cash_bank_transaction_id", "bank_account_id",
                       "cash_account_type", "installment_amount"):
            batch.drop_column(column)
        batch.drop_constraint("ck_employee_charges_type", type_="check")
        batch.create_check_constraint("ck_employee_charges_type", "charge_type IN ('DENDA', 'GANTI_RUGI')")
