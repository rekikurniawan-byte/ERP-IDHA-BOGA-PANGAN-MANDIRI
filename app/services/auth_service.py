from werkzeug.security import check_password_hash
from app.models.master import User


def authenticate_user(username, password):
    user = User.query.filter_by(username=username).first()

    if not user:
        return None, "Username tidak ditemukan."

    if not user.is_active:
        return None, "User tidak aktif."

    if not check_password_hash(user.password_hash, password):
        return None, "Password salah."

    return user, None
