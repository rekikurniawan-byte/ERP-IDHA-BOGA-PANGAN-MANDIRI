"""Isi awal database baru: COA acuan, cabang pertama, dan OWNER pertama.

Gladi pilot 2026-09-28 menemukan bahwa database yang dibangun dari nol oleh
migrasi hanya berisi 4 akun COA dan tidak punya cabang maupun user -- tidak ada
yang bisa login, dan setiap jurnal gagal karena akun wajib tidak ada.

COA di bawah adalah COA acuan owner (keputusan 2026-09-25: "COA di database
adalah acuan"), disalin dari database staging. Semua fungsi di sini aman
dijalankan berulang: yang sudah ada tidak diubah.
"""
from werkzeug.security import generate_password_hash

from app.extensions import db

DEFAULT_CHART_OF_ACCOUNTS = (
    ("1001", "Kas", "ASSET"),
    ("1002", "Bank 1", "ASSET"),
    ("1003", "Bank 2", "ASSET"),
    ("1004", "Piutang Usaha", "ASSET"),
    ("1005", "Piutang Karyawan / Warung", "ASSET"),
    ("1006", "Persediaan Bahan Baku", "ASSET"),
    ("1008", "Uang Muka / DP", "ASSET"),
    ("1009", "Pajak Dibayar di Muka (PPh 23/25)", "ASSET"),
    ("1101", "Peralatan Dapur", "ASSET"),
    ("1102", "Kendaraan Operasional", "ASSET"),
    ("1103", "Bangunan / Dapur", "ASSET"),
    ("2001", "Hutang Usaha / Pembiayaan", "LIABILITY"),
    ("2002", "Hutang Supplier", "LIABILITY"),
    ("2003", "Hutang Gaji", "LIABILITY"),
    ("2004", "Hutang Operasional", "LIABILITY"),
    ("2005", "Hutang Transport", "LIABILITY"),
    ("2006", "Hutang Lain-lain", "LIABILITY"),
    ("2007", "Deposit Jaminan Pelanggan", "LIABILITY"),
    ("2008", "Uang Muka Pelanggan", "LIABILITY"),
    # Ta'zir (Fase 7): dana titipan untuk disalurkan, bukan pendapatan.
    ("2009", "Dana Sosial (Ta'zir)", "LIABILITY"),
    # Pajak (Fase 8): PBJT titipan konsumen, bukan pendapatan.
    ("2010", "Hutang PBJT", "LIABILITY"),
    ("2101", "Akumulasi Penyusutan Peralatan", "CONTRA_ASSET"),
    ("2102", "Akumulasi Penyusutan Kendaraan", "CONTRA_ASSET"),
    ("2103", "Akumulasi Penyusutan Bangunan", "CONTRA_ASSET"),
    ("3001", "Modal Pemilik", "EQUITY"),
    ("3002", "Laba Ditahan", "EQUITY"),
    ("3003", "Prive / Pengambilan Pemilik", "EQUITY"),
    ("4001", "Pendapatan Catering Proyek", "REVENUE"),
    ("4002", "Pendapatan Catering Harian", "REVENUE"),
    ("4003", "Pendapatan Warung", "REVENUE"),
    ("4004", "Pendapatan Lain-Lain", "REVENUE"),
    ("4005", "Pendapatan Ongkos Kirim", "REVENUE"),
    ("5001", "HPP Bahan Baku", "EXPENSE"),
    ("5002", "Beban Operasional Dapur", "EXPENSE"),
    ("5003", "Beban Transport / BBM", "EXPENSE"),
    ("5004", "Beban Gaji", "EXPENSE"),
    ("5005", "Beban Listrik", "EXPENSE"),
    ("5006", "Beban Air", "EXPENSE"),
    ("5007", "Beban Gas LPG", "EXPENSE"),
    ("5008", "Beban Administrasi / Bunga", "EXPENSE"),
    ("5009", "Beban Lain-Lain", "EXPENSE"),
    ("5010", "Beban Kemasan", "EXPENSE"),
    ("5011", "Beban Perawatan Kendaraan", "EXPENSE"),
    ("5012", "Beban Penyusutan", "EXPENSE"),
    ("5013", "Beban Piutang Tak Tertagih", "EXPENSE"),
    ("5014", "Beban PPh Final", "EXPENSE"),
)


class BootstrapError(ValueError):
    pass


def ensure_chart_of_accounts():
    """Tambahkan akun acuan yang belum ada. Akun yang sudah ada tidak diubah. Tidak commit."""
    from app.models.accounting import Account

    existing = {row.account_code for row in Account.query.all()}
    created = []
    for code, name, kind in DEFAULT_CHART_OF_ACCOUNTS:
        if code not in existing:
            db.session.add(Account(account_code=code, account_name=name, account_type=kind, is_active=True))
            created.append(code)
    db.session.flush()
    return created


def bootstrap_company(*, branch_code, branch_name, owner_username, owner_full_name, owner_password):
    """COA + cabang pertama + OWNER pertama, dalam satu commit. Aman diulang."""
    from app.models.master import Branch, User
    from app.services.user_management_service import normalize_username, validate_password_pair

    created_accounts = ensure_chart_of_accounts()

    branch = Branch.query.filter_by(code=branch_code).first()
    branch_created = branch is None
    if branch_created:
        if not (branch_name or "").strip():
            raise BootstrapError("Nama cabang wajib diisi.")
        branch = Branch(code=branch_code, name=branch_name.strip(), is_active=True)
        db.session.add(branch)
        db.session.flush()

    owner = User.query.filter_by(role="OWNER").order_by(User.id).first()
    owner_created = owner is None
    if owner_created:
        username = normalize_username(owner_username)
        if not username:
            raise BootstrapError("Username OWNER wajib diisi.")
        valid, message = validate_password_pair(owner_password or "", owner_password or "")
        if not valid:
            raise BootstrapError(message)
        owner = User(
            branch_id=branch.id,
            full_name=(owner_full_name or "Owner").strip(),
            username=username,
            password_hash=generate_password_hash(owner_password),
            role="OWNER",
            is_active=True,
        )
        db.session.add(owner)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {
        "accounts_created": created_accounts,
        "branch": branch,
        "branch_created": branch_created,
        "owner": owner,
        "owner_created": owner_created,
    }
