"""Kontrol kredit: credit_accounts, credit_status_events, identitas mandor, akun baru.

Tahap A dari BLUEPRINT_V2_KONTROL_KREDIT.md.

Satu-satunya data yang diisi adalah tiga akun COA baru (lihat NEW_ACCOUNTS),
dan hanya kalau kodenya belum ada. Selebihnya murni DDL. Aturannya:
tidak ada baris akun kredit berarti tidak ada kredit -- pihak itu ditagih lewat
PT pemilik proyek (VIA_CLIENT), limit 0, status AKTIF, persis seperti sebelum
migrasi ini. Baris akun baru dibuat saat owner benar-benar menyetel kredit
untuk seseorang. Lihat credit_control_service.resolve_billing_party().

Versi pertama migrasi ini mengisi satu baris per pasangan client x cabang.
Karena client itu global, jumlahnya tumbuh sebagai client x cabang: 30 baris di
staging, tapi sekitar 7 juta di database test yang berisi seed menumpuk --
padahal hampir semua pasangan itu tidak pernah bertransaksi. Mengisi data
netral juga tidak menambah keamanan apa pun, karena baris yang tidak ada sudah
dinilai netral.

Ambang eskalasi juga tidak ditulis ke branch_settings: nilai bawaannya ada di
credit_control_service.DEFAULT_THRESHOLDS, dan baris branch_settings dengan
key credit.* hanya menimpa nilai itu untuk satu cabang.

Revision ID: a0b1c2d3e4f5
Revises: 99a0a1b2c3d4
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa


revision = "a0b1c2d3e4f5"
down_revision = "99a0a1b2c3d4"
branch_labels = None
depends_on = None


# Keputusan owner 2026-09-25. Deposit jaminan dan DP client adalah uang yang
# DITERIMA, jadi kewajiban -- bukan 1008 yang berjenis aset. Hapus buku piutang
# butuh akun beban sendiri.
NEW_ACCOUNTS = (
    # Diganti menjadi "Deposit Jaminan Pelanggan" oleh migrasi a2b3c4d5e6f7.
    ("2007", "Deposit Jaminan Mandor", "LIABILITY"),
    ("2008", "Uang Muka Pelanggan", "LIABILITY"),
    ("5013", "Beban Piutang Tak Tertagih", "EXPENSE"),
)

# Dibaca tests/test_optimistic_locking_models.py dan
# tests/test_numeric_migration_coverage.py, seperti migrasi-migrasi sebelumnya.
VERSIONED_TABLES = ("credit_accounts", "credit_status_events")
MONEY_COLUMNS = {
    "credit_accounts": ("credit_limit",),
    "credit_status_events": ("exposure_amount", "credit_limit"),
}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {"credit_accounts": ("deposit_percent",)}


def upgrade():
    op.create_table(
        "credit_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("party_type", sa.String(length=20), nullable=False),
        sa.Column("party_id", sa.Integer(), nullable=False),
        sa.Column("billing_mode", sa.String(length=20), nullable=False, server_default="VIA_CLIENT"),
        sa.Column("credit_limit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False, server_default="0"),
        # Syarat deposit (persen dari limit). Deposit yang sudah diterima tidak
        # disimpan di sini: dihitung dari transaksi deposit di buku besar.
        sa.Column("deposit_percent", sa.Numeric(8, 4), nullable=False, server_default="20"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="AKTIF"),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(), nullable=True),
        sa.Column("status_changed_by", sa.Integer(), nullable=True),
        sa.Column("release_until", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.UniqueConstraint("branch_id", "party_type", "party_id", name="uq_credit_accounts_party"),
    )
    op.create_index("ix_credit_accounts_branch_id", "credit_accounts", ["branch_id"])
    op.create_index("ix_credit_accounts_status", "credit_accounts", ["status"])

    op.create_table(
        "credit_status_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("credit_account_id", sa.Integer(), sa.ForeignKey("credit_accounts.id"), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("exposure_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("credit_limit", sa.Numeric(18, 2), nullable=True),
        sa.Column("oldest_days_overdue", sa.Integer(), nullable=True),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_credit_status_events_branch_id", "credit_status_events", ["branch_id"])
    op.create_index("ix_credit_status_events_account", "credit_status_events", ["credit_account_id"])

    # Identitas mandor. Nullable: mandor lama yang ditagih lewat PT tidak boleh
    # ikut terhambat hanya karena NIK-nya belum pernah dicatat.
    op.add_column("mandors", sa.Column("id_number", sa.String(length=32), nullable=True))
    op.add_column("mandors", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("mandors", sa.Column("guarantor_name", sa.String(length=150), nullable=True))
    op.add_column("mandors", sa.Column("guarantor_phone", sa.String(length=30), nullable=True))
    op.add_column("mandors", sa.Column("guarantor_id_number", sa.String(length=32), nullable=True))
    op.create_index("ix_mandors_id_number", "mandors", ["id_number"])

    # Akun baru. Dimasukkan hanya kalau kodenya belum ada, supaya COA yang
    # sudah disusun owner tidak pernah ditimpa.
    bind = op.get_bind()
    for code, name, account_type in NEW_ACCOUNTS:
        bind.execute(
            sa.text(
                "INSERT INTO accounts (created_at, version_id, account_code, account_name, account_type, is_active) "
                "SELECT NOW(), 1, CAST(:code AS VARCHAR), CAST(:name AS VARCHAR), CAST(:type AS VARCHAR), true "
                "WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE account_code = CAST(:code AS VARCHAR))"
            ),
            {"code": code, "name": name, "type": account_type},
        )


def downgrade():
    bind = op.get_bind()
    # Ambang yang sempat ditimpa per cabang ikut dibuang bersama fiturnya.
    bind.execute(sa.text("DELETE FROM branch_settings WHERE setting_key LIKE 'credit.%'"))

    # Akun baru hanya dihapus kalau belum pernah dijurnal. Akun yang sudah
    # punya jurnal dibiarkan: menghapusnya akan merusak buku besar.
    for code, _, _ in NEW_ACCOUNTS:
        bind.execute(
            sa.text(
                "DELETE FROM accounts a WHERE a.account_code = CAST(:code AS VARCHAR) "
                "AND NOT EXISTS (SELECT 1 FROM journal_details jd WHERE jd.account_id = a.id)"
            ),
            {"code": code},
        )

    op.drop_index("ix_mandors_id_number", table_name="mandors")
    for column in (
        "guarantor_id_number", "guarantor_phone", "guarantor_name",
        "address", "id_number",
    ):
        op.drop_column("mandors", column)

    op.drop_index("ix_credit_status_events_account", table_name="credit_status_events")
    op.drop_index("ix_credit_status_events_branch_id", table_name="credit_status_events")
    op.drop_table("credit_status_events")

    op.drop_index("ix_credit_accounts_status", table_name="credit_accounts")
    op.drop_index("ix_credit_accounts_branch_id", table_name="credit_accounts")
    op.drop_table("credit_accounts")
