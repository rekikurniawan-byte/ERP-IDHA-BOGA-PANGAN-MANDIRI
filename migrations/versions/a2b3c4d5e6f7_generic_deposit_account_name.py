"""Nama akun COA 2007 dibuat umum: "Deposit Jaminan Pelanggan".

Keputusan owner 2026-09-26: sistem dipakai untuk pelanggan katering di luar
proyek, dan istilah seperti "Mandor" kini diatur per cabang. Nama akun di
buku besar tidak boleh ikut berubah-ubah per cabang, jadi akun deposit
jaminan yang dibuat migrasi a0b1c2d3e4f5 diberi nama baku yang umum.

Hanya mengganti nama kalau masih nama lama, supaya nama yang sudah diubah
owner sendiri tidak ditimpa.

Revision ID: a2b3c4d5e6f7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa


revision = "a2b3c4d5e6f7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

OLD_NAME = "Deposit Jaminan Mandor"
NEW_NAME = "Deposit Jaminan Pelanggan"


def _rename(old, new):
    op.get_bind().execute(
        sa.text(
            "UPDATE accounts SET account_name = CAST(:new AS VARCHAR) "
            "WHERE account_code = '2007' AND account_name = CAST(:old AS VARCHAR)"
        ),
        {"old": old, "new": new},
    )


def upgrade():
    _rename(OLD_NAME, NEW_NAME)


def downgrade():
    _rename(NEW_NAME, OLD_NAME)
