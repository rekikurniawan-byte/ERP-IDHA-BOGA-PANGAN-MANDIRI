from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.master import Branch, User


ROLE_OWNER = "OWNER"
ROLE_ADMIN = "ADMIN"
ROLE_FINANCE = "FINANCE"
ROLE_ACCOUNTING = "ACCOUNTING"
ROLE_LOGISTICS = "LOGISTICS"
ROLE_HR = "HR"
ROLE_DAPUR = "DAPUR"
ROLE_PENGANTAR = "PENGANTAR"
ROLE_CUSTOMER_SUCCESS = "CUSTOMER_SUCCESS"
# Client and PT are one role: a client IS the company, and it sees every sub
# client under its contract. PORTAL_PT is retired into this one.
ROLE_PORTAL_CLIENT = "PORTAL_CLIENT"
ROLE_PORTAL_SUBCLIENT = "PORTAL_SUBCLIENT"
ROLE_PORTAL_DELEGATE = "PORTAL_DELEGATE"
ROLE_PORTAL_CUSTOMER = "PORTAL_CUSTOMER"

PORTAL_EXTERNAL_ROLES = {
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_SUBCLIENT,
    ROLE_PORTAL_DELEGATE,
    ROLE_PORTAL_CUSTOMER,
}

PORTAL_ROLE_LANDING_ENDPOINTS = {
    ROLE_PORTAL_CUSTOMER: "portal.customer_dashboard",
    ROLE_PORTAL_SUBCLIENT: "portal.mandor_dashboard",
    # The merged role lands on the PT home -- the company view over every sub
    # client. client_dashboard is the narrower page and is no longer a landing.
    ROLE_PORTAL_CLIENT: "portal.pt_dashboard",
    ROLE_PORTAL_DELEGATE: "portal.delegate_dashboard",
}

# Roles a user can be given. Blueprint V2 leaves four internal roles and
# three portal roles.
#
# FINANCE, ACCOUNTING, LOGISTICS, HR and CUSTOMER_SUCCESS are retired: ADMIN
# does their work, and app/utils/roles.py maps any allowlist or stored row
# naming them to ADMIN. Their ROLE_* constants stay because route allowlists
# still reference them.
#
# PORTAL_DELEGATE is retired too, but deliberately NOT mapped to a successor:
# the owner confirmed nobody logs in as a delegate, and a delegate was a
# narrower view than a client, so quietly promoting one would widen access.
# It simply stops being assignable; any row still holding it gets no portal
# scope. Its code paths are still present and are a follow-up cleanup.
ALLOWED_ROLES = [
    ROLE_OWNER,
    ROLE_ADMIN,
    ROLE_DAPUR,
    ROLE_PENGANTAR,
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_SUBCLIENT,
    ROLE_PORTAL_CUSTOMER,
]

ROLE_LABELS = {
    ROLE_OWNER: "Owner / Pemilik",
    ROLE_ADMIN: "Admin Operasional",
    ROLE_FINANCE: "Finance",
    ROLE_ACCOUNTING: "Accounting",
    ROLE_LOGISTICS: "Logistics / Stok",
    ROLE_HR: "HR / SDM",
    ROLE_DAPUR: "Dapur / Produksi",
    ROLE_PENGANTAR: "Pengantar / Delivery",
    ROLE_CUSTOMER_SUCCESS: "Customer Success",
    ROLE_PORTAL_CLIENT: "Portal Client / PT",
    ROLE_PORTAL_SUBCLIENT: "Portal Sub Client / Mandor",
    ROLE_PORTAL_DELEGATE: "Portal Delegasi",
    ROLE_PORTAL_CUSTOMER: "Portal Pelanggan Umum",
}

ROLE_DESCRIPTIONS = {
    ROLE_OWNER: "Akses penuh, pengaturan sistem, backup, user, audit, dan semua modul.",
    ROLE_ADMIN: "Akses operasional penuh: order, keuangan, akuntansi, stok & pembelian, SDM & payroll, dan customer success.",
    ROLE_FINANCE: "Disiapkan untuk invoice, pembayaran, kas/bank, piutang, hutang supplier, dan profit invoice.",
    ROLE_ACCOUNTING: "Disiapkan untuk jurnal, laporan akuntansi, COA mapping, opening balance, dan closing/checking.",
    ROLE_LOGISTICS: "Disiapkan untuk stok, prediksi bahan, pembelian, supplier, kartu stok, dan bukti nota.",
    ROLE_HR: "Disiapkan untuk karyawan internal dan payroll. Mandor tetap bukan employee/payroll.",
    ROLE_DAPUR: "Akses produksi dapur, permintaan bahan, dan pemakaian dapur.",
    ROLE_PENGANTAR: "Akses pengiriman, penerimaan, riwayat delivery, dan bukti digital delivery.",
    ROLE_CUSTOMER_SUCCESS: "Akses kontrak customer, komplain, koreksi, bukti pendukung, dan koordinasi tindak lanjut tanpa posting langsung ke finance/stok.",
    ROLE_PORTAL_CLIENT: "Akses portal read-only untuk Client/PT: seluruh sub client, invoice, piutang, pembayaran, dan kontrak perusahaannya.",
    ROLE_PORTAL_SUBCLIENT: "Akses portal read-only untuk Sub Client / Mandor berdasarkan mapping eksplisit.",
    ROLE_PORTAL_DELEGATE: "Akses portal read-only terbatas untuk delegasi Client/PIC/lokasi.",
    ROLE_PORTAL_CUSTOMER: "Role reservasi pelanggan umum; akses transaksi tetap menunggu mapping dan approval lanjutan.",
}

MIN_PASSWORD_LENGTH = 8


def get_role_label(role):
    return ROLE_LABELS.get(role, role or "-")


def get_role_description(role):
    return ROLE_DESCRIPTIONS.get(role, "")


def get_portal_role_landing_endpoint(role):
    return PORTAL_ROLE_LANDING_ENDPOINTS.get(role)


def normalize_username(username):
    return (username or "").strip().lower()


def clean_text(value):
    return (value or "").strip()


def list_users(branch_id=None):
    query = User.query

    if branch_id is not None:
        query = query.filter(User.branch_id == branch_id)

    return query.order_by(User.role.asc(), User.username.asc()).all()


def list_active_branches():
    return Branch.query.filter_by(is_active=True).order_by(Branch.name.asc()).all()


def get_user_or_404(user_id):
    return User.query.get_or_404(user_id)


def username_is_used(username, exclude_id=None):
    username = normalize_username(username)
    query = User.query.filter(User.username == username)

    if exclude_id:
        query = query.filter(User.id != exclude_id)

    return query.first() is not None


def validate_password_pair(password, confirmation):
    if not password or not confirmation:
        return False, "Password dan konfirmasi password wajib diisi."

    if password != confirmation:
        return False, "Konfirmasi password tidak sama."

    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password minimal {MIN_PASSWORD_LENGTH} karakter."

    return True, None


def active_owner_count(exclude_user_id=None):
    query = User.query.filter(User.role == "OWNER", User.is_active == True)

    if exclude_user_id:
        query = query.filter(User.id != exclude_user_id)

    return query.count()


def validate_user_payload(form, existing_user=None, current_user=None):
    full_name = clean_text(form.get("full_name"))
    username = normalize_username(form.get("username"))
    role = clean_text(form.get("role"))
    branch_id_raw = clean_text(form.get("branch_id"))
    is_active = form.get("is_active") == "on"

    if not full_name:
        return None, "Nama lengkap wajib diisi."

    if not username:
        return None, "Username wajib diisi."

    if role not in ALLOWED_ROLES:
        return None, "Role tidak valid."

    try:
        branch_id = int(branch_id_raw)
    except (TypeError, ValueError):
        return None, "Cabang wajib dipilih."

    branch = Branch.query.get(branch_id)
    if not branch or not branch.is_active:
        return None, "Cabang tidak valid atau tidak aktif."

    exclude_id = existing_user.id if existing_user else None
    if username_is_used(username, exclude_id=exclude_id):
        return None, "Username sudah digunakan user lain."

    if existing_user and current_user and existing_user.id == current_user.id:
        # User boleh edit nama/username sendiri, tetapi role/cabang/status tidak boleh berubah dari form.
        role = existing_user.role
        branch_id = existing_user.branch_id
        is_active = existing_user.is_active

    if existing_user and existing_user.role == "OWNER" and role != "OWNER":
        if active_owner_count(exclude_user_id=existing_user.id) <= 0:
            return None, "Tidak boleh mengubah role OWNER terakhir."

    if existing_user and existing_user.role == "OWNER" and existing_user.is_active and not is_active:
        if active_owner_count(exclude_user_id=existing_user.id) <= 0:
            return None, "Tidak boleh menonaktifkan OWNER terakhir."

    return {
        "full_name": full_name,
        "username": username,
        "role": role,
        "branch_id": branch_id,
        "is_active": is_active,
    }, None


def create_user(form):
    payload, error = validate_user_payload(form)
    if error:
        return None, error

    password = form.get("password") or ""
    password_confirmation = form.get("password_confirmation") or ""
    valid_password, password_error = validate_password_pair(password, password_confirmation)
    if not valid_password:
        return None, password_error

    user = User(
        full_name=payload["full_name"],
        username=payload["username"],
        role=payload["role"],
        branch_id=payload["branch_id"],
        is_active=payload["is_active"],
        password_hash=generate_password_hash(password),
    )

    db.session.add(user)
    db.session.commit()
    return user, None


def update_user(user, form, current_user):
    payload, error = validate_user_payload(form, existing_user=user, current_user=current_user)
    if error:
        return None, error

    user.full_name = payload["full_name"]
    user.username = payload["username"]
    user.role = payload["role"]
    user.branch_id = payload["branch_id"]
    user.is_active = payload["is_active"]

    db.session.commit()
    return user, None


def toggle_user_active(user, current_user):
    if user.id == current_user.id:
        return False, "Tidak boleh menonaktifkan akun yang sedang digunakan."

    if user.role == "OWNER" and user.is_active:
        if active_owner_count(exclude_user_id=user.id) <= 0:
            return False, "Tidak boleh menonaktifkan OWNER terakhir."

    user.is_active = not user.is_active
    db.session.commit()
    return True, None


def reset_user_password(user, new_password, confirmation, current_user):
    if user.id == current_user.id:
        return False, "Gunakan menu Ganti Password untuk mengganti password akun sendiri."

    valid_password, error = validate_password_pair(new_password, confirmation)
    if not valid_password:
        return False, error

    if user.role == "OWNER" and current_user.role != "OWNER":
        return False, "Reset password OWNER hanya boleh dilakukan oleh OWNER."

    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    return True, None


def change_own_password(user, current_password, new_password, confirmation):
    if not check_password_hash(user.password_hash, current_password or ""):
        return False, "Password lama tidak sesuai."

    valid_password, error = validate_password_pair(new_password, confirmation)
    if not valid_password:
        return False, error

    if check_password_hash(user.password_hash, new_password):
        return False, "Password baru tidak boleh sama dengan password lama."

    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    return True, None
