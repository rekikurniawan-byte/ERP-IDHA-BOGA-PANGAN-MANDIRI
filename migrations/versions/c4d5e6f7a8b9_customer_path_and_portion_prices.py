"""Dua jalur transaksi (tahap 1): jalur pelanggan dan daftar harga per porsi.

Keputusan owner 2026-09-27:
- setiap client punya jalur: KONTRAK (kredit lewat invoice) atau UMUM (bayar
  di muka). Client yang dibuat lewat pendaftaran portal pelanggan umum ditandai
  UMUM; sisanya KONTRAK, seperti perilakunya selama ini;
- harga per porsi (sama untuk siang dan malam) dari daftar harga yang bisa
  diubah kapan saja dengan tanggal berlaku: harga kontrak per client menang atas
  harga standar cabang;
- harga yang terpakai dikunci ke order/draft saat dibuat, dengan asalnya.

Order lama tidak disentuh: price_source kosong berarti harga diketik manual
sebelum daftar harga ada.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa


revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None

# Dibaca tests/test_optimistic_locking_models.py dan
# tests/test_numeric_migration_coverage.py, seperti migrasi-migrasi sebelumnya.
VERSIONED_TABLES = ("portion_prices",)
MONEY_COLUMNS = {
    "portion_prices": ("price_per_portion",),
    "portal_order_drafts": ("price_per_portion",),
}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}


def upgrade():
    op.add_column(
        "clients",
        sa.Column("customer_path", sa.String(length=20), nullable=False, server_default="KONTRAK"),
    )
    op.create_check_constraint("ck_clients_customer_path", "clients", "customer_path IN ('KONTRAK', 'UMUM')")
    # UMUM hanya kalau SEMUA akun portal yang terkait client itu (langsung atau
    # lewat sub client-nya) adalah pelanggan umum. Client kontrak yang kebetulan
    # dipetakan ke akun pelanggan (data demo) tetap KONTRAK.
    op.get_bind().execute(
        sa.text(
            "WITH linked AS ("
            "  SELECT COALESCE(m.client_id, md.client_id) AS client_id, u.role "
            "  FROM portal_user_mappings m "
            "  JOIN users u ON u.id = m.user_id "
            "  LEFT JOIN mandors md ON md.id = m.mandor_id"
            ") "
            "UPDATE clients SET customer_path = 'UMUM' WHERE id IN ("
            "  SELECT client_id FROM linked WHERE client_id IS NOT NULL "
            "  GROUP BY client_id HAVING bool_and(role = 'PORTAL_CUSTOMER')"
            ")"
        )
    )

    op.create_table(
        "portion_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("price_per_portion", sa.Numeric(18, 2), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("price_per_portion > 0", name="ck_portion_prices_positive"),
    )
    op.create_index("ix_portion_prices_lookup", "portion_prices", ["branch_id", "client_id", "effective_from"])

    op.add_column("daily_order_details", sa.Column("price_source", sa.String(length=20), nullable=True))
    op.add_column("portal_order_drafts", sa.Column("price_per_portion", sa.Numeric(18, 2), nullable=True))
    op.add_column("portal_order_drafts", sa.Column("price_source", sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column("portal_order_drafts", "price_source")
    op.drop_column("portal_order_drafts", "price_per_portion")
    op.drop_column("daily_order_details", "price_source")
    op.drop_index("ix_portion_prices_lookup", table_name="portion_prices")
    op.drop_table("portion_prices")
    op.drop_constraint("ck_clients_customer_path", "clients", type_="check")
    op.drop_column("clients", "customer_path")
