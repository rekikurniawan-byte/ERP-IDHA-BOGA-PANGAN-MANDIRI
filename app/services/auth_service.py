from werkzeug.security import check_password_hash
from app.models.master import User


INVALID_LOGIN_MESSAGE = "Username atau password tidak valid."


def authenticate_user(username, password):
    user = User.query.filter_by(username=username).first()

    if not user:
        return None, INVALID_LOGIN_MESSAGE

    if not user.is_active:
        return None, INVALID_LOGIN_MESSAGE

    if not check_password_hash(user.password_hash, password):
        return None, INVALID_LOGIN_MESSAGE

    return user, None
