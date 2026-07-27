from types import SimpleNamespace

from werkzeug.security import generate_password_hash

from app.services import auth_service


class _FakeQuery:
    def __init__(self, user):
        self.user = user

    def filter_by(self, **kwargs):
        return self

    def first(self):
        return self.user


def _patch_user_query(monkeypatch, user):
    monkeypatch.setattr(auth_service, "User", SimpleNamespace(query=_FakeQuery(user)))


def test_authenticate_user_uses_generic_message_for_unknown_username(monkeypatch):
    _patch_user_query(monkeypatch, None)

    user, error = auth_service.authenticate_user("unknown", "password")

    assert user is None
    assert error == auth_service.INVALID_LOGIN_MESSAGE


def test_authenticate_user_uses_generic_message_for_wrong_password(monkeypatch):
    _patch_user_query(
        monkeypatch,
        SimpleNamespace(
            is_active=True,
            password_hash=generate_password_hash("correct-password"),
        ),
    )

    user, error = auth_service.authenticate_user("owner", "wrong-password")

    assert user is None
    assert error == auth_service.INVALID_LOGIN_MESSAGE


def test_authenticate_user_uses_generic_message_for_inactive_user(monkeypatch):
    _patch_user_query(
        monkeypatch,
        SimpleNamespace(
            is_active=False,
            password_hash=generate_password_hash("correct-password"),
        ),
    )

    user, error = auth_service.authenticate_user("disabled", "correct-password")

    assert user is None
    assert error == auth_service.INVALID_LOGIN_MESSAGE


def test_authenticate_user_accepts_active_user_with_valid_password(monkeypatch):
    expected_user = SimpleNamespace(
        is_active=True,
        password_hash=generate_password_hash("correct-password"),
    )
    _patch_user_query(monkeypatch, expected_user)

    user, error = auth_service.authenticate_user("owner", "correct-password")

    assert user is expected_user
    assert error is None
