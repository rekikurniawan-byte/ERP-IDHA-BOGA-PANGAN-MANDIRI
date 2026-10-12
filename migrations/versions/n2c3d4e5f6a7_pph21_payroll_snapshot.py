"""PPh 21 karyawan: status PTKP/NPWP di karyawan + snapshot PPh 21 per baris gaji.

Aturan & tarif ada di modul pajak (tax_pph21_service); tabel ini hanya
menyimpan identitas karyawan dan hasil hitungan yang dibekukan saat penggajian.

Revision ID: n2c3d4e5f6a7
Revises: m1b2c3d4e5f6
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa


revision = "n2c3d4e5f6a7"
down_revision = "m1b2c3d4e5f6"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {"payroll_details": ("tax_bruto", "pph21_amount")}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {"payroll_details": ("ter_rate",)}
VERSIONED_TABLES = ()


def upgrade():
    with op.batch_alter_table("employees") as batch:
        batch.add_column(sa.Column("ptkp_status", sa.String(length=5), nullable=True))
        batch.add_column(sa.Column("npwp", sa.String(length=25), nullable=True))

    with op.batch_alter_table("payroll_details") as batch:
        batch.add_column(sa.Column("tax_bruto", sa.Numeric(18, 2), nullable=True))
        batch.add_column(sa.Column("pph21_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
        batch.add_column(sa.Column("pph21_method", sa.String(length=10), nullable=True))
        batch.add_column(sa.Column("ter_category", sa.String(length=1), nullable=True))
        batch.add_column(sa.Column("ter_rate", sa.Numeric(8, 4), nullable=True))
        batch.add_column(sa.Column("pph21_borne_by", sa.String(length=12), nullable=True))
        batch.add_column(sa.Column("ptkp_status", sa.String(length=5), nullable=True))
        batch.add_column(sa.Column("pph21_note", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("payroll_details") as batch:
        batch.drop_column("pph21_note")
        batch.drop_column("ptkp_status")
        batch.drop_column("pph21_borne_by")
        batch.drop_column("ter_rate")
        batch.drop_column("ter_category")
        batch.drop_column("pph21_method")
        batch.drop_column("pph21_amount")
        batch.drop_column("tax_bruto")

    with op.batch_alter_table("employees") as batch:
        batch.drop_column("npwp")
        batch.drop_column("ptkp_status")
