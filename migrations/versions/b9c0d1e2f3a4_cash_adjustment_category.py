"""Penyesuaian kas/bank punya jenis: selisih hitung, biaya admin bank, bunga bank.

Keputusan owner 2026-09-28 (poin 8-9): setiap penyesuaian langsung dijurnal,
dan akun lawannya ditentukan jenisnya (selisih lebih 4004, selisih kurang 5009,
biaya admin 5008, bunga 4004). Penyesuaian lama dianggap selisih hitung.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa


revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cash_bank_adjustments",
        sa.Column("adjustment_category", sa.String(length=30), nullable=False, server_default="SELISIH"),
    )


def downgrade():
    op.drop_column("cash_bank_adjustments", "adjustment_category")
