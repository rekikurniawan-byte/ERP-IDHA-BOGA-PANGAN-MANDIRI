from functools import wraps

from flask import flash, redirect, url_for
from flask_login import current_user, login_required


def role_required(*allowed_roles):
    def decorator(function):
        @wraps(function)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.role == "OWNER":
                return function(*args, **kwargs)

            if current_user.role not in allowed_roles:
                flash("Akses ditolak. Role kamu tidak memiliki izin membuka halaman ini.", "danger")
                return redirect(url_for("dashboard.index"))

            return function(*args, **kwargs)

        return wrapper

    return decorator
