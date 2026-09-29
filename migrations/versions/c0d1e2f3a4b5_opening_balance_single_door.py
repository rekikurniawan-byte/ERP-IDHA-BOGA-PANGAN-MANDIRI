"""Saldo awal satu pintu.

Keputusan owner 2026-09-28 (poin 1-5): saldo awal diisi di satu halaman per
cabang dan dikunci sekaligus.

- opening_balances: draf + status kunci per cabang.
- opening_balance_corrections: koreksi beralasan sesudah dikunci.
- stock_opening_balances.unit_cost: harga stok awal (nilai 1006 dan harga rata-rata).
- supplier_bills.procurement_id boleh kosong: hutang lama tanpa pembelian di sistem.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa


revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None

# Dibaca tes cakupan Numeric dan optimistic locking.
MONEY_COLUMNS = {"stock_opening_balances": ["unit_cost"]}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}
VERSIONED_TABLES = ("opening_balances", "opening_balance_corrections")


def upgrade():
    op.create_table(
        "opening_balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False, unique=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("journals.id"), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("locked_by", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
    )
    op.create_index("ix_opening_balances_status", "opening_balances", ["status"])
    op.create_table(
        "opening_balance_corrections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("opening_balance_id", sa.Integer(), sa.ForeignKey("opening_balances.id"), nullable=False),
        sa.Column("section", sa.String(length=30), nullable=False),
        sa.Column("line_key", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("journals.id"), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
    )
    op.create_index("ix_opening_balance_corrections_opening_balance_id", "opening_balance_corrections", ["opening_balance_id"])
    op.add_column("stock_opening_balances", sa.Column("unit_cost", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.alter_column("supplier_bills", "procurement_id", existing_type=sa.Integer(), nullable=True)


def downgrade():
    op.alter_column("supplier_bills", "procurement_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("stock_opening_balances", "unit_cost")
    op.drop_index("ix_opening_balance_corrections_opening_balance_id", table_name="opening_balance_corrections")
    op.drop_table("opening_balance_corrections")
    op.drop_index("ix_opening_balances_status", table_name="opening_balances")
    op.drop_table("opening_balances")
