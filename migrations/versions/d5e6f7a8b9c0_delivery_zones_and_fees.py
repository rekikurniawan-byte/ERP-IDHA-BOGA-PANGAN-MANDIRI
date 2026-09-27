"""Dua jalur transaksi (tahap 2): ongkir.

Keputusan owner 2026-09-27:
- kontrak: ongkir sudah termasuk harga porsi, kecuali kontraknya menyebut ongkir
  per pengiriman (baris delivery_fees dengan client_id);
- umum: tarif per zona, per pengiriman (siang dan malam = dua kali jalan),
  gratis kalau porsi pengiriman itu mencapai ambang cabang;
- tarif bisa diubah kapan saja (BBM) dengan tanggal berlaku, dan dikunci ke
  pengiriman saat pesanan dibuat;
- ongkir tercatat di akun baru 4005 Pendapatan Ongkos Kirim, supaya bisa
  dibandingkan dengan 5003 Beban Transport / BBM.

Order lama tidak disentuh: ongkirnya 0, seperti selama ini.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa


revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None

# Dibaca tests/test_optimistic_locking_models.py dan
# tests/test_numeric_migration_coverage.py, seperti migrasi-migrasi sebelumnya.
VERSIONED_TABLES = ("delivery_zones", "delivery_fees")
MONEY_COLUMNS = {
    "delivery_fees": ("fee",),
    "daily_order_details": ("lunch_delivery_fee", "dinner_delivery_fee"),
    "portal_order_drafts": ("delivery_fee",),
}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}

DELIVERY_REVENUE_CODE = "4005"
DELIVERY_REVENUE_NAME = "Pendapatan Ongkos Kirim"


def upgrade():
    op.create_table(
        "delivery_zones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("branch_id", "name", name="uq_delivery_zones_branch_name"),
    )
    op.create_index("ix_delivery_zones_branch_id", "delivery_zones", ["branch_id"])

    op.create_table(
        "delivery_fees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("zone_id", sa.Integer(), sa.ForeignKey("delivery_zones.id"), nullable=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("fee", sa.Numeric(18, 2), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("fee >= 0", name="ck_delivery_fees_not_negative"),
        sa.CheckConstraint("(zone_id IS NULL) <> (client_id IS NULL)", name="ck_delivery_fees_one_target"),
    )
    op.create_index(
        "ix_delivery_fees_lookup", "delivery_fees", ["branch_id", "zone_id", "client_id", "effective_from"]
    )

    op.add_column(
        "delivery_locations",
        sa.Column("delivery_zone_id", sa.Integer(), sa.ForeignKey("delivery_zones.id"), nullable=True),
    )
    op.add_column(
        "daily_order_details",
        sa.Column("lunch_delivery_fee", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "daily_order_details",
        sa.Column("dinner_delivery_fee", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )
    op.add_column("portal_order_drafts", sa.Column("delivery_fee", sa.Numeric(18, 2), nullable=True))

    op.get_bind().execute(
        sa.text(
            "INSERT INTO accounts (account_code, account_name, account_type, is_active, created_at, version_id) "
            "SELECT CAST(:code AS VARCHAR), CAST(:name AS VARCHAR), 'REVENUE', true, now(), 1 "
            "WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE account_code = CAST(:code AS VARCHAR))"
        ),
        {"code": DELIVERY_REVENUE_CODE, "name": DELIVERY_REVENUE_NAME},
    )


def downgrade():
    # Akun 4005 hanya dihapus kalau belum pernah dipakai jurnal.
    op.get_bind().execute(
        sa.text(
            "DELETE FROM accounts WHERE account_code = CAST(:code AS VARCHAR) "
            "AND NOT EXISTS (SELECT 1 FROM journal_details d WHERE d.account_id = accounts.id)"
        ),
        {"code": DELIVERY_REVENUE_CODE},
    )
    op.drop_column("portal_order_drafts", "delivery_fee")
    op.drop_column("daily_order_details", "dinner_delivery_fee")
    op.drop_column("daily_order_details", "lunch_delivery_fee")
    op.drop_column("delivery_locations", "delivery_zone_id")
    op.drop_index("ix_delivery_fees_lookup", table_name="delivery_fees")
    op.drop_table("delivery_fees")
    op.drop_index("ix_delivery_zones_branch_id", table_name="delivery_zones")
    op.drop_table("delivery_zones")
