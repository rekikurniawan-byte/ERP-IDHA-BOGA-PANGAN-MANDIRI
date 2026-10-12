"""Apel: tanda surat dokter (sakit bersurat dokter tetap dibayar).

Revision ID: m1b2c3d4e5f6
Revises: l0a1b2c3d4e5
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa


revision = "m1b2c3d4e5f6"
down_revision = "l0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("employee_attendance") as batch:
        batch.add_column(sa.Column("medical_note", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("employee_attendance") as batch:
        batch.drop_column("medical_note")
