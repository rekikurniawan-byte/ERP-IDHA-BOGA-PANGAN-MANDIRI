import re
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.master import Branch, User
from app.utils.terms import L, T


ROLE_OWNER = "OWNER"
ROLE_ADMIN = "ADMIN"
ROLE_ADMIN_OPERASIONAL = "ADMIN_OPERASIONAL"
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
ROLE_PORTAL_CUSTOMER = "PORTAL_CUSTOMER"

PORTAL_EXTERNAL_ROLES = {
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_SUBCLIENT,
    ROLE_PORTAL_CUSTOMER,
}

PORTAL_ROLE_LANDING_ENDPOINTS = {
    ROLE_PORTAL_CUSTOMER: "portal.customer_dashboard",
    ROLE_PORTAL_SUBCLIENT: "portal.mandor_dashboard",
    # The merged role lands on the PT home -- the company view over every sub
    # client. client_dashboard is the narrower page and is no longer a landing.
    ROLE_PORTAL_CLIENT: "portal.pt_dashboard",
}

# Roles a user can be given. Blueprint V2 leaves four internal roles and
# three portal roles.
#
# FINANCE, ACCOUNTING, LOGISTICS, HR and CUSTOMER_SUCCESS are retired: ADMIN
# does their work, and app/utils/roles.py maps any allowlist or stored row
# naming them to ADMIN. Their ROLE_* constants stay because route allowlists
# still reference them.
#
# PORTAL_DELEGATE is retired too, and deliberately NOT mapped to a successor:
# the owner confirmed nobody logs in as a delegate, and a delegate was a
# narrower view than a client, so quietly promoting one would widen access.
# Its code paths are gone; a row still holding it is not a portal role and
# gets no portal scope and no landing page. The DELEGATE *mapping* principal
# in portal_mapping_service is a different thing and is still live: every
# self-registered portal customer gets one.
ALLOWED_ROLES = [
    ROLE_OWNER,
    ROLE_ADMIN,
    ROLE_ADMIN_OPERASIONAL,
    ROLE_DAPUR,
    ROLE_PENGANTAR,
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_SUBCLIENT,
    ROLE_PORTAL_CUSTOMER,
]

ROLE_LABELS = {
    ROLE_OWNER: "Owner / Pemilik",
    ROLE_ADMIN: "Admin",
    ROLE_ADMIN_OPERASIONAL: "Admin Operasional",
    ROLE_FINANCE: "Finance",
    ROLE_ACCOUNTING: "Accounting",
    ROLE_LOGISTICS: "Logistics / Stok",
    ROLE_HR: "HR / SDM",
    ROLE_DAPUR: "Dapur / Produksi",
    ROLE_PENGANTAR: "Pengantar / Delivery",
    ROLE_CUSTOMER_SUCCESS: "Customer Success",
    ROLE_PORTAL_CLIENT: L("Portal {client}"),
    ROLE_PORTAL_SUBCLIENT: L("Portal {sub_client}"),
    ROLE_PORTAL_CUSTOMER: "Portal Pelanggan Umum",
}

ROLE_DESCRIPTIONS = {
    ROLE_OWNER: "Akses penuh, pengaturan sistem, backup, user, audit, dan semua modul.",
    ROLE_ADMIN: "Akses operasional penuh: order, keuangan, akuntansi, stok & pembelian, SDM & payroll, dan customer success.",
    ROLE_ADMIN_OPERASIONAL: "Hanya operasional: pesanan harian, draf portal, jadwal menu, produksi, pengiriman, dan serah terima (tanpa akses keuangan, akuntansi, HR, atau master/pengaturan).",
    ROLE_FINANCE: "Disiapkan untuk invoice, pembayaran, kas/bank, piutang, hutang supplier, dan profit invoice.",
    ROLE_ACCOUNTING: "Disiapkan untuk jurnal, laporan akuntansi, COA mapping, opening balance, dan closing/checking.",
    ROLE_LOGISTICS: "Disiapkan untuk stok, prediksi bahan, pembelian, supplier, kartu stok, dan bukti nota.",
    ROLE_HR: L("Disiapkan untuk karyawan internal dan payroll. {sub_client} tetap bukan employee/payroll."),
    ROLE_DAPUR: "Akses produksi dapur, permintaan bahan, dan pemakaian dapur.",
    ROLE_PENGANTAR: "Akses pengiriman, penerimaan, riwayat delivery, dan bukti digital delivery.",
    ROLE_CUSTOMER_SUCCESS: "Akses kontrak customer, komplain, koreksi, bukti pendukung, dan koordinasi tindak lanjut tanpa posting langsung ke finance/stok.",
    ROLE_PORTAL_CLIENT: L("Akses portal satu {client}: seluruh {sub_client_lower}, invoice, piutang, pembayaran, dan kontrak perusahaannya. Memesan hanya lewat Order langsung."),
    ROLE_PORTAL_SUBCLIENT: L("Akses portal satu {sub_client_lower}: pesan untuk lokasinya sendiri (dikonfirmasi admin), invoice, pembayaran, dan hutang."),
    ROLE_PORTAL_CUSTOMER: "Pelanggan umum. Mendaftar sendiri lewat halaman Daftar di portal; akunnya otomatis terhubung ke lokasi antarnya.",
}

MIN_PASSWORD_LENGTH = 8


def get_role_label(role):
    return ROLE_LABELS.get(role, role or "-")


def get_portal_role_landing_endpoint(role):
    return PORTAL_ROLE_LANDING_ENDPOINTS.get(role)


EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_username(username):
    if username is None:
        return ""
    return str(username).strip().lower()


def normalize_email(email):
    if email is None:
        return ""
    return str(email).strip().lower()


def is_valid_email_format(email):
    if not email or len(email) > 150:
        return False
    return bool(EMAIL_REGEX.match(email))


def email_is_used(email, exclude_id=None):
    normalized = normalize_email(email)
    if not normalized:
        return False
    query = User.query.filter(func.lower(User.email) == normalized)
    if exclude_id is not None:
        query = query.filter(User.id != exclude_id)
    return query.first() is not None


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


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
    email_raw = clean_text(form.get("email"))
    email = normalize_email(email_raw)

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

    if role in PORTAL_EXTERNAL_ROLES and not email:
        return None, "Email wajib diisi untuk akun portal."

    if email:
        if not is_valid_email_format(email):
            return None, "Format email tidak valid."
        if email_is_used(email, exclude_id=exclude_id):
            return None, "Email ini sudah dipakai akun lain."

    if role == ROLE_PORTAL_CUSTOMER and not (existing_user and existing_user.role == ROLE_PORTAL_CUSTOMER):
        return None, (
            "Pelanggan umum mendaftar sendiri lewat halaman Daftar di portal, "
            "supaya akunnya langsung terhubung ke lokasi antar dan zona ongkirnya."
        )

    portal_link, portal_error = _validate_portal_link(role, form, branch_id)
    if portal_error:
        return None, portal_error

    if existing_user and existing_user.role == "OWNER" and role != "OWNER":
        if active_owner_count(exclude_user_id=existing_user.id) <= 0:
            return None, "Tidak boleh mengubah role OWNER terakhir."

    if existing_user and existing_user.role == "OWNER" and existing_user.is_active and not is_active:
        if active_owner_count(exclude_user_id=existing_user.id) <= 0:
            return None, "Tidak boleh menonaktifkan OWNER terakhir."

    phone = clean_text(form.get("phone")) or None
    address = clean_text(form.get("address")) or None

    return {
        "full_name": full_name,
        "username": username,
        "email": email or None,
        "phone": phone,
        "address": address,
        "role": role,
        "branch_id": branch_id,
        "is_active": is_active,
        **portal_link,
    }, None


def create_user(form, acted_by=None):
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
        email=payload.get("email"),
        phone=payload.get("phone"),
        address=payload.get("address"),
        role=payload["role"],
        branch_id=payload["branch_id"],
        is_active=payload["is_active"],
        password_hash=generate_password_hash(password),
    )

    db.session.add(user)
    db.session.flush()
    sync_portal_link(user, client_id=payload.get("portal_client_id"), mandor_id=payload.get("portal_mandor_id"), acted_by=acted_by)
    db.session.commit()
    return user, None


def update_user(user, form, current_user):
    payload, error = validate_user_payload(form, existing_user=user, current_user=current_user)
    if error:
        return None, error

    user.full_name = payload["full_name"]
    user.username = payload["username"]
    user.email = payload.get("email")
    if "phone" in form:
        user.phone = payload.get("phone")
    if "address" in form:
        user.address = payload.get("address")
    user.role = payload["role"]
    user.branch_id = payload["branch_id"]
    user.is_active = payload["is_active"]
    sync_portal_link(
        user,
        client_id=payload.get("portal_client_id"),
        mandor_id=payload.get("portal_mandor_id"),
        acted_by=getattr(current_user, "id", None),
    )

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


def change_own_password(user, current_password, new_password, confirmation, *, commit=True):
    if not check_password_hash(user.password_hash, current_password or ""):
        return False, "Password lama tidak sesuai."

    valid_password, error = validate_password_pair(new_password, confirmation)
    if not valid_password:
        return False, error

    if check_password_hash(user.password_hash, new_password):
        return False, "Password baru tidak boleh sama dengan password lama."

    user.password_hash = generate_password_hash(new_password)
    if commit:
        db.session.commit()
    return True, None


def update_portal_user_email(user, new_email, current_password):
    if not user.password_hash or not check_password_hash(user.password_hash, current_password or ""):
        return False, "Password saat ini tidak sesuai."

    cleaned_email = normalize_email(new_email)
    if not cleaned_email:
        return False, "Email wajib diisi."

    if not is_valid_email_format(cleaned_email):
        return False, "Format email tidak valid."

    if email_is_used(cleaned_email, exclude_id=user.id):
        return False, "Email ini sudah dipakai akun lain."

    old_email = user.email
    user.email = cleaned_email
    db.session.commit()

    from app.services.audit_log_service import record_critical_audit_log

    record_critical_audit_log(
        module="PORTAL",
        event_type="PORTAL_EMAIL_UPDATED",
        action="UPDATE",
        table_name="users",
        record_id=user.id,
        description=f"Email akun portal {user.username} diperbarui.",
        old_value=old_email,
        new_value=cleaned_email,
        metadata={
            "user_id": user.id,
            "username": user.username,
            "old_email": old_email,
            "new_email": cleaned_email,
        },
    )
    return True, None


# --- akun portal PT / Mandor --------------------------------------------------
# Keputusan owner 2026-09-28 (gladi pilot): OWNER menghubungkan akun portal di
# form User; satu akun = satu PT atau satu mandor. Portal PT memantau seluruh
# mandornya dan hanya memesan lewat Order langsung (orderable_location_ids);
# Portal Mandor memesan untuk lokasinya sendiri, tetap dikonfirmasi admin.
# Pelanggan umum terhubung sendiri saat mendaftar (pemetaan DELEGATE).
PORTAL_LINK_PRINCIPALS = {ROLE_PORTAL_CLIENT: "CLIENT", ROLE_PORTAL_SUBCLIENT: "MANDOR"}


def portal_link_options():
    """Pilihan PT kontrak dan mandor-nya untuk form User."""
    from app.models.master import Client, Mandor
    from app.services.pricing_service import PATH_CONTRACT

    clients = (
        Client.query.filter(Client.is_active.is_(True), Client.customer_path == PATH_CONTRACT)
        .order_by(Client.name.asc()).all()
    )
    mandors = (
        Mandor.query.outerjoin(Client, Client.id == Mandor.client_id)
        .filter(
            Mandor.is_active.is_(True),
            Mandor.is_direct_unit.is_(False),
            db.or_(Mandor.client_id.is_(None), Client.customer_path == PATH_CONTRACT),
        )
        .order_by(Mandor.name.asc()).all()
    )
    return {"clients": clients, "mandors": mandors}


def current_portal_link(user):
    """PT/mandor yang sekarang terhubung ke akun ini ({} kalau belum ada)."""
    from app.models.system import PortalUserMapping

    if not getattr(user, "id", None):
        return {}
    row = (
        PortalUserMapping.query.filter(
            PortalUserMapping.user_id == user.id,
            PortalUserMapping.is_active.is_(True),
            PortalUserMapping.principal_type.in_(tuple(PORTAL_LINK_PRINCIPALS.values())),
        )
        .order_by(PortalUserMapping.id.desc()).first()
    )
    if not row:
        return {}
    if row.principal_type == "CLIENT":
        label = row.client.name if row.client else "-"
    else:
        label = row.mandor.name if row.mandor else "-"
        if row.mandor and row.mandor.client:
            label = f"{label} ({row.mandor.client.name})"
    return {"client_id": row.client_id, "mandor_id": row.mandor_id, "label": label}


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _validate_portal_link(role, form, branch_id):
    from app.models.master import Client, Mandor
    from app.services.pricing_service import PATH_CONTRACT

    principal = PORTAL_LINK_PRINCIPALS.get(role)
    if principal == "CLIENT":
        client = Client.query.get(_int_or_none(form.get("portal_client_id")) or 0)
        if not client or not client.is_active or client.customer_path != PATH_CONTRACT:
            return None, f"Pilih {T.client} kontrak yang dihubungkan ke akun Portal {T.client} ini."
        return {"portal_client_id": client.id}, None
    if principal == "MANDOR":
        mandor = Mandor.query.get(_int_or_none(form.get("portal_mandor_id")) or 0)
        valid = (
            mandor is not None and mandor.is_active and not mandor.is_direct_unit
            and mandor.branch_id == branch_id
            and (mandor.client is None or mandor.client.customer_path == PATH_CONTRACT)
        )
        if not valid:
            return None, f"Pilih {T.sub_client_lower} aktif di cabang akun ini untuk akun Portal {T.sub_client}."
        return {"portal_mandor_id": mandor.id}, None
    return {}, None


def sync_portal_link(user, *, client_id=None, mandor_id=None, acted_by=None):
    """Samakan pemetaan PT/mandor akun ini dengan pilihan form. Tidak commit.

    Pemetaan lain yang aktif dinonaktifkan (satu akun = satu PT/mandor), dan
    akun yang pindah ke role non-portal kehilangan aksesnya. Pemetaan pelanggan
    umum (DELEGATE) tidak disentuh.
    """
    from datetime import datetime

    from app.models.system import PortalUserMapping

    principal = PORTAL_LINK_PRINCIPALS.get(user.role)
    target = client_id if principal == "CLIENT" else mandor_id
    kept = None
    for row in PortalUserMapping.query.filter(
        PortalUserMapping.user_id == user.id,
        PortalUserMapping.is_active.is_(True),
        PortalUserMapping.principal_type.in_(tuple(PORTAL_LINK_PRINCIPALS.values())),
    ).all():
        same = row.principal_type == principal and (row.client_id if principal == "CLIENT" else row.mandor_id) == target
        if same and kept is None:
            kept = row
            continue
        row.is_active = False
        row.updated_at = datetime.utcnow()
        row.updated_by = acted_by
    if principal and target and kept is None:
        db.session.add(PortalUserMapping(
            user_id=user.id,
            principal_type=principal,
            client_id=target if principal == "CLIENT" else None,
            mandor_id=target if principal == "MANDOR" else None,
            access_level="DRAFT_ORDER",
            is_active=True,
            created_by=acted_by,
        ))
    db.session.flush()


def portal_account_rows(branch_id=None):
    """Akun portal beserta PT / mandor / lokasi yang terhubung, untuk halaman Pengaturan Akses Portal."""
    from app.models.system import PortalUserMapping

    query = User.query.filter(User.role.in_(sorted(PORTAL_EXTERNAL_ROLES)))
    if branch_id is not None:
        query = query.filter(User.branch_id == branch_id)
    rows = []
    for user in query.order_by(User.role.asc(), User.full_name.asc()).all():
        if user.role == ROLE_PORTAL_CUSTOMER:
            locations = [
                mapping.delivery_location.location_name
                for mapping in PortalUserMapping.query.filter_by(user_id=user.id, is_active=True).all()
                if mapping.delivery_location
            ]
            link = ", ".join(locations)
        else:
            link = current_portal_link(user).get("label", "")
        rows.append({"user": user, "role_label": get_role_label(user.role), "link": link})
    return rows
