from functools import wraps

from flask import flash, redirect, url_for
from flask_login import current_user, login_required

from app.utils.roles import role_permits


def role_required(*allowed_roles):
    # allowed_roles may still name roles retired by the Blueprint V2
    # consolidation (FINANCE, ACCOUNTING, ...). role_permits() maps them to
    # their successor, so those routes now admit ADMIN -- see app/utils/roles.py.
    def decorator(function):
        @wraps(function)
        @login_required
        def wrapper(*args, **kwargs):
            if not role_permits(current_user.role, allowed_roles):
                flash("Akses ditolak. Role kamu tidak memiliki izin membuka halaman ini.", "danger")
                return redirect(url_for("dashboard.index"))

            return function(*args, **kwargs)

        return wrapper

    return decorator


def module_required(module_name):
    """Halaman milik modul cabang (Warung / Hutang Pekerja).

    Pasang di bawah role_required, supaya pengguna sudah pasti login. Modul
    mati = halaman ditolak dengan pesan, termasuk untuk OWNER: ini pilihan
    bisnis cabang, bukan hak akses.
    """
    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            from app.services.branch_module_service import module_enabled, module_off_message

            if not module_enabled(module_name):
                flash(module_off_message(module_name), "warning")
                if str(current_user.role or "").startswith("PORTAL_"):
                    return redirect(url_for("portal.my_dashboard"))
                return redirect(url_for("dashboard.index"))

            return function(*args, **kwargs)

        return wrapper

    return decorator
