"""Dua jalur transaksi (tahap 4): jalur dicatat di setiap invoice.

Keputusan owner 2026-09-27: pendapatan dipilah menurut jalur pelanggan --
KONTRAK ke 4001, UMUM ke 4002 -- dan laporan bisa dipisah per jalur. Jalur
dikunci di invoice saat dibuat, supaya client yang kemudian pindah jalur tidak
mengubah laporan invoice lamanya.

Invoice lama diberi label jalur dari client-nya sekarang; ini hanya label
laporan. Jumlah invoice dan jurnal yang sudah ada tidak disentuh.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa


revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("invoices", sa.Column("customer_path", sa.String(length=20), nullable=True))
    op.create_index("ix_invoices_customer_path", "invoices", ["customer_path"])
    op.get_bind().execute(
        sa.text(
            "UPDATE invoices SET customer_path = c.customer_path "
            "FROM clients c WHERE c.id = invoices.client_id AND invoices.customer_path IS NULL"
        )
    )


def downgrade():
    op.drop_index("ix_invoices_customer_path", table_name="invoices")
    op.drop_column("invoices", "customer_path")
