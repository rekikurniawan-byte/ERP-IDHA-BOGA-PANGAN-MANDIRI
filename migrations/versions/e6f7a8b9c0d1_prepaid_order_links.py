"""Dua jalur transaksi (tahap 3): uang muka terkait pesanan pelanggan umum.

Keputusan owner 2026-09-27: pelanggan umum bayar di muka. Bukti bayar yang
diverifikasi Finance menjadi Uang Muka Pelanggan (2008) dengan jurnal otomatis,
dan uang muka itu dipakai melunasi invoice pesanannya setelah semua
pengiriman diterima. Dua kolom ini menghubungkan uang muka ke draft portal dan
ke baris order, supaya pelunasan dan pengembalian dana tidak menebak.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa


revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "advance_transactions",
        sa.Column("portal_order_draft_id", sa.Integer(), sa.ForeignKey("portal_order_drafts.id"), nullable=True),
    )
    op.add_column(
        "advance_transactions",
        sa.Column("daily_order_detail_id", sa.Integer(), sa.ForeignKey("daily_order_details.id"), nullable=True),
    )
    op.create_index("ix_advance_transactions_portal_order_draft_id", "advance_transactions", ["portal_order_draft_id"])
    op.create_index("ix_advance_transactions_daily_order_detail_id", "advance_transactions", ["daily_order_detail_id"])


def downgrade():
    op.drop_index("ix_advance_transactions_daily_order_detail_id", table_name="advance_transactions")
    op.drop_index("ix_advance_transactions_portal_order_draft_id", table_name="advance_transactions")
    op.drop_column("advance_transactions", "daily_order_detail_id")
    op.drop_column("advance_transactions", "portal_order_draft_id")
