"""Aturan potong upah hari tidak bekerja dikunci per kontrak kerja.

Revision ID: l0a1b2c3d4e5
Revises: k9f0a1b2c3d4
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa


revision = "l0a1b2c3d4e5"
down_revision = "k9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    # Kontrak yang sudah ada hanya menjanjikan potongan untuk "tanpa keterangan".
    with op.batch_alter_table("employment_contracts") as batch:
        batch.add_column(sa.Column("unpaid_statuses", sa.String(length=60), nullable=False, server_default="ALPA"))
        batch.add_column(sa.Column("daily_wage_divisor", sa.String(length=10), nullable=False, server_default="KALENDER"))


def downgrade():
    with op.batch_alter_table("employment_contracts") as batch:
        batch.drop_column("daily_wage_divisor")
        batch.drop_column("unpaid_statuses")
