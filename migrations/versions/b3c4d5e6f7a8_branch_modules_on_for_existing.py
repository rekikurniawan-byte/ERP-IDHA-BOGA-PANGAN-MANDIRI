"""Modul Warung dan Hutang Pekerja dinyalakan untuk cabang yang sudah ada.

Keputusan owner 2026-09-27: Warung dan Hutang Pekerja menjadi modul per
cabang (Pengaturan Perusahaan -> Modul). Pengaturan yang tidak ada berarti
MATI, supaya cabang baru -- misalnya katering sekolah -- mulai tanpa fitur
proyek. Cabang yang sudah berjalan memakai kedua modul itu, jadi migrasi ini
menulis "1" untuk mereka: tidak ada yang berubah bagi cabang lama.

Hanya mengisi yang belum ada, supaya pilihan yang sudah disimpan owner tidak
ditimpa. Tidak ada data transaksi yang disentuh.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa


revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None

MODULE_KEYS = ("module_warung", "module_worker_debt")


def upgrade():
    bind = op.get_bind()
    for key in MODULE_KEYS:
        bind.execute(
            sa.text(
                "INSERT INTO branch_settings (branch_id, setting_key, setting_value, created_at, version_id) "
                "SELECT b.id, CAST(:key AS VARCHAR), '1', now(), 1 FROM branches b "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM branch_settings s WHERE s.branch_id = b.id AND s.setting_key = CAST(:key AS VARCHAR)"
                ")"
            ),
            {"key": key},
        )


def downgrade():
    op.get_bind().execute(
        sa.text("DELETE FROM branch_settings WHERE setting_key IN ('module_warung', 'module_worker_debt')")
    )
