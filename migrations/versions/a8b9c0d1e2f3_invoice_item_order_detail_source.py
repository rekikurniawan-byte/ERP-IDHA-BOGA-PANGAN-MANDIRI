"""Item invoice dari order harian memakai satu nama sumber: ORDER_DETAIL.

Gladi pilot 2026-09-28: invoice per order (termasuk invoice otomatis pelanggan
umum) menandai itemnya DAILY_ORDER_DETAIL, sedangkan invoice periode dan
pembacanya -- Cek Kesehatan Data, laporan catering, jejak order sampai lunas,
laba per invoice -- memakai ORDER_DETAIL. Akibatnya pesanan yang sudah ditagih
dan lunas tetap tampil "Belum masuk invoice".

Hanya label sumber item yang berubah; nominal invoice dan jurnal tidak disentuh.

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa


revision = "a8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text(
        "UPDATE invoice_items SET source_type = 'ORDER_DETAIL' WHERE source_type = 'DAILY_ORDER_DETAIL'"
    ))


def downgrade():
    # Item invoice order harian (invoice.source_type = DAILY_ORDER) dulu bernama
    # DAILY_ORDER_DETAIL; item invoice periode memang ORDER_DETAIL sejak awal.
    op.get_bind().execute(sa.text(
        "UPDATE invoice_items SET source_type = 'DAILY_ORDER_DETAIL' "
        "WHERE source_type = 'ORDER_DETAIL' "
        "AND invoice_id IN (SELECT id FROM invoices WHERE source_type = 'DAILY_ORDER')"
    ))
