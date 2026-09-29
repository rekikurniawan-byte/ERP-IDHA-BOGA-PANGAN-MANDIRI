"""Cek kesiapan produksi: `flask --app run ops-check`.

Penilaian pra-produksi 2026-09-27 (BLUEPRINT_V2_AUDIT_FITUR.md, langkah 5).
Hanya membaca -- tidak ada yang ditulis. Setiap cek menghasilkan FAIL (harus
dibereskan sebelum dipakai), WARN (perlu diputuskan), atau PASS.

Dipakai tiga kali: sebelum go-live, setiap hari lewat penjadwal (hasil FAIL
membuat unit systemd gagal dan terlihat di `systemctl --failed`), dan selama
uji coba satu cabang.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text

from app.extensions import db

FAIL, WARN, PASS = "FAIL", "WARN", "PASS"

REQUIRED_ACCOUNTS = {
    "1001": "Kas", "1002": "Bank", "1004": "Piutang Usaha", "1005": "Piutang Karyawan",
    "2007": "Deposit Jaminan Pelanggan", "2008": "Uang Muka Pelanggan",
    "4001": "Pendapatan Catering Proyek", "4002": "Pendapatan Catering Harian",
    "4003": "Pendapatan Warung", "4004": "Pendapatan Lain-Lain", "4005": "Pendapatan Ongkos Kirim",
    "5003": "Beban Transport / BBM",
}


@dataclass
class Check:
    status: str
    name: str
    message: str


def _migration_check():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from flask import current_app
    import os

    script = ScriptDirectory.from_config(Config(os.path.join(current_app.root_path, "..", "migrations", "alembic.ini")))
    heads = set(script.get_heads())
    current = {row[0] for row in db.session.execute(text("SELECT version_num FROM alembic_version"))}
    if current == heads:
        return Check(PASS, "Migrasi", f"Database di revisi terbaru ({', '.join(sorted(current))}).")
    return Check(FAIL, "Migrasi", f"Database di {sorted(current)}, kode di {sorted(heads)}. Jalankan `flask db upgrade`.")


def _table_owner_check():
    """Aplikasi harus bisa baca-tulis semua tabel miliknya sendiri.

    Tabel yang dibuat migrasi dengan user database lain membuat aplikasi kena
    'permission denied' (pernah terjadi di staging). Tabel di luar model
    aplikasi -- mis. tabel sistem ML/SPK yang terpisah -- tidak dinilai.
    """
    app_tables = sorted(db.metadata.tables)
    denied = [
        table for table in app_tables
        if not db.session.execute(
            text("SELECT has_table_privilege(current_user, :table, 'SELECT,INSERT,UPDATE,DELETE')"),
            {"table": table},
        ).scalar()
    ]
    if not denied:
        return Check(PASS, "Hak akses tabel", f"User aplikasi bisa baca-tulis {len(app_tables)} tabel aplikasi.")
    return Check(
        FAIL, "Hak akses tabel",
        f"{len(denied)} tabel aplikasi tidak bisa ditulis user aplikasi (mis. {', '.join(denied[:5])}). "
        "Jalankan migrasi dengan DATABASE_URL aplikasi, atau ALTER TABLE ... OWNER TO user aplikasi.",
    )


def _config_checks():
    from flask import current_app

    config = current_app.config
    checks = []
    if config.get("IS_PRODUCTION") and config.get("DEBUG"):
        checks.append(Check(FAIL, "Mode debug", "DEBUG aktif di produksi."))
    else:
        checks.append(Check(PASS, "Mode debug", "DEBUG tidak aktif di produksi."))
    cutover = config.get("ACCOUNTING_LEGACY_CUTOVER") or {}
    if cutover:
        checks.append(Check(
            WARN, "Cutover akuntansi",
            f"ACCOUNTING_LEGACY_CUTOVER={cutover}: transaksi ber-ID <= angka itu tidak dijurnal. "
            "Kosongkan untuk database produksi baru.",
        ))
    else:
        checks.append(Check(PASS, "Cutover akuntansi", "Kosong: tidak ada transaksi yang dilewati jurnalnya."))
    return checks


def _account_check():
    from app.models.accounting import Account

    active = {row.account_code for row in Account.query.filter(Account.is_active.is_(True)).all()}
    missing = [f"{code} {name}" for code, name in REQUIRED_ACCOUNTS.items() if code not in active]
    if missing:
        return Check(FAIL, "Akun COA", "Belum ada/aktif: " + "; ".join(missing))
    return Check(PASS, "Akun COA", f"{len(REQUIRED_ACCOUNTS)} akun wajib tersedia dan aktif.")


def _contract_pic_check():
    """Invoice kontrak baru bisa disimpan kalau client punya PIC resmi aktif (gladi pilot 2026-09-28)."""
    from app.models.master import Client, ClientPic, Mandor
    from app.services.pricing_service import PATH_CONTRACT

    in_use = (
        Client.query.join(Mandor, Mandor.client_id == Client.id)
        .filter(Client.is_active.is_(True), Client.customer_path == PATH_CONTRACT, Mandor.is_active.is_(True))
        .distinct().all()
    )
    with_pic = {row.client_id for row in ClientPic.query.filter(ClientPic.is_active.is_(True)).all()}
    missing = sorted(client.name for client in in_use if client.id not in with_pic)
    if missing:
        return Check(
            WARN, "PIC client kontrak",
            f"{len(missing)} client kontrak belum punya PIC resmi aktif (mis. {', '.join(missing[:3])}): "
            "invoicenya belum bisa disimpan. Tambahkan di Master Client > PIC.",
        )
    return Check(PASS, "PIC client kontrak", f"{len(in_use)} client kontrak aktif punya PIC resmi.")


def _portal_check():
    """Portal dipakai pelanggan umum untuk daftar & bayar di muka, dan mandor untuk memesan."""
    from flask import current_app

    from app.models.master import User
    from app.services.user_management_service import PORTAL_LINK_PRINCIPALS, current_portal_link

    if not current_app.config.get("PORTAL_ENABLED"):
        return Check(
            WARN, "Portal",
            "PORTAL_ENABLED mati: pelanggan umum tidak bisa daftar/pesan dan akun portal tidak bisa login. "
            "Isi PORTAL_ENABLED=1 di .env kalau portal dipakai.",
        )
    accounts = User.query.filter(User.role.in_(sorted(PORTAL_LINK_PRINCIPALS)), User.is_active.is_(True)).all()
    unlinked = sorted(user.username for user in accounts if not current_portal_link(user))
    if unlinked:
        return Check(
            WARN, "Portal",
            f"{len(unlinked)} akun portal belum terhubung ke PT/mandor (mis. {', '.join(unlinked[:3])}). "
            "Hubungkan di Pengaturan > User.",
        )
    return Check(PASS, "Portal", f"Portal aktif; {len(accounts)} akun PT/mandor terhubung.")


def _subledger_check():
    """Setiap buku pembantu harus sama dengan saldo akunnya di buku besar.

    Semua transaksi dijurnal bersama pencatatannya, jadi selisih berarti ada
    yang lolos tanpa jurnal, jurnal manual di akun kontrol, atau data lama.
    """
    from app.services.subledger_check_service import subledger_lines

    differences = [
        f"{line.label} ({line.accounts}): buku besar Rp {line.ledger:,.0f}, {line.source} Rp {line.subledger:,.0f}"
        for line in subledger_lines() if not line.ok
    ]
    if differences:
        return Check(FAIL, "Buku pembantu vs buku besar", "; ".join(differences) + ". Rinciannya di Cek Kesehatan Data.")
    return Check(PASS, "Buku pembantu vs buku besar", "Kas, bank, piutang, hutang supplier, persediaan, dan aset sama dengan buku besar.")


def _stock_journal_check():
    from app.services.subledger_check_service import unjournaled_stock_movements

    missing = unjournaled_stock_movements()
    if missing:
        return Check(
            WARN, "Jurnal pergerakan stok",
            f"{len(missing)} pergerakan stok belum dijurnal (barangnya belum punya harga pembelian, atau data lama). "
            "Lihat Akuntansi > Status Posting.",
        )
    return Check(PASS, "Jurnal pergerakan stok", "Semua pergerakan stok yang mengubah nilai persediaan sudah dijurnal.")


def _branch_checks(branch_ids=None):
    from app.models.master import Branch, Client, DeliveryLocation, Mandor
    from app.models.pricing import DeliveryZone
    from app.services.company_settings_service import get_company_settings
    from app.services.pricing_service import PATH_GENERAL, fee_in_effect, quote_price

    checks = []
    query = Branch.query.filter(Branch.is_active.is_(True))
    if branch_ids is not None:
        query = query.filter(Branch.id.in_(branch_ids))
    from app.services.opening_balance_service import is_locked

    for branch in query.order_by(Branch.id).all():
        label = f"Cabang {branch.name}"
        if is_locked(branch.id):
            checks.append(Check(PASS, f"{label}: saldo awal", "Saldo awal sudah dikunci."))
        else:
            checks.append(Check(
                FAIL, f"{label}: saldo awal",
                "Saldo awal belum dikunci: kas, piutang, hutang, stok, dan aset lama belum masuk buku. Isi di Akuntansi > Saldo Awal.",
            ))
        if quote_price(branch.id, None) is None:
            checks.append(Check(FAIL, f"{label}: harga", "Harga standar per porsi belum diatur: pesanan baru ditolak."))
        else:
            checks.append(Check(PASS, f"{label}: harga", "Harga standar per porsi berlaku."))

        settings = get_company_settings(branch.id)
        if not (settings.get("payment_account_number") or "").strip():
            checks.append(Check(WARN, f"{label}: rekening", "Rekening pembayaran perusahaan belum diisi: invoice & instruksi bayar tanpa rekening."))

        general_locations = (
            DeliveryLocation.query.join(Mandor, Mandor.id == DeliveryLocation.mandor_id)
            .join(Client, Client.id == Mandor.client_id)
            .filter(Mandor.branch_id == branch.id, Client.customer_path == PATH_GENERAL, DeliveryLocation.is_active.is_(True))
            .all()
        )
        without_zone = [location.location_name for location in general_locations if not location.delivery_zone_id]
        if without_zone:
            checks.append(Check(
                FAIL, f"{label}: zona ongkir",
                f"{len(without_zone)} lokasi pelanggan umum belum punya zona (mis. {', '.join(without_zone[:3])}): pesanannya ditolak.",
            ))
        zones_without_fee = [
            zone.name for zone in DeliveryZone.query.filter_by(branch_id=branch.id, is_active=True).all()
            if fee_in_effect(branch.id, zone_id=zone.id) is None
        ]
        if zones_without_fee:
            checks.append(Check(FAIL, f"{label}: tarif ongkir", f"Zona tanpa tarif: {', '.join(zones_without_fee)}."))
    return checks


def _backup_check(max_age_hours=26):
    from app.services.backup_service import list_full_backups

    backups = sorted(list_full_backups(), key=lambda row: row.get("created_at") or datetime.min.astimezone(), reverse=True)
    if not backups:
        return Check(FAIL, "Backup", "Belum ada backup penuh. Jalankan `flask --app run backup-full` dan jadwalkan harian.")
    latest = backups[0]
    age = datetime.now().astimezone() - latest["created_at"]
    if age > timedelta(hours=max_age_hours):
        return Check(FAIL, "Backup", f"Backup penuh terakhir {latest['name']} berumur {age.days} hari {age.seconds // 3600} jam.")
    return Check(PASS, "Backup", f"Backup penuh terakhir {latest['name']} ({age.seconds // 3600} jam lalu).")


def run_readiness_checks(branch_ids=None):
    """branch_ids membatasi cek per cabang (bawaan: semua cabang aktif)."""
    checks = []
    for step in (_migration_check, _table_owner_check, _account_check, _backup_check, _contract_pic_check, _subledger_check,
                 _stock_journal_check, _portal_check):
        try:
            checks.append(step())
        except Exception as error:  # noqa: BLE001 - satu cek gagal tidak boleh menghentikan laporan
            checks.append(Check(FAIL, step.__name__.strip("_").replace("_check", ""), f"Cek gagal dijalankan: {error}"))
    checks.extend(_config_checks())
    checks.extend(_branch_checks(branch_ids))
    return checks
