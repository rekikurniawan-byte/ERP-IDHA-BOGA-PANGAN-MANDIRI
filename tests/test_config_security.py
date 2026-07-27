import pytest

from config import DEFAULT_CONTENT_SECURITY_POLICY, _validate_production_security_config


def test_production_security_config_allows_development_defaults():
    _validate_production_security_config(
        app_env="development",
        debug=True,
        secret_key="change-this-local-secret-key",
        session_cookie_secure=False,
        trusted_hosts=None,
        ratelimit_storage_uri="memory://",
    )


def test_production_security_config_rejects_insecure_production_values():
    with pytest.raises(RuntimeError) as exc_info:
        _validate_production_security_config(
            app_env="production",
            debug=True,
            secret_key="replace-with-a-long-random-secret-key",
            session_cookie_secure=False,
            trusted_hosts=None,
            ratelimit_storage_uri="memory://",
        )

    message = str(exc_info.value)
    assert "APP_DEBUG/FLASK_DEBUG harus 0" in message
    assert "SECRET_KEY production harus acak" in message
    assert "SESSION_COOKIE_SECURE harus aktif" in message
    assert "TRUSTED_HOSTS wajib diisi" in message
    assert "RATELIMIT_STORAGE_URI production tidak boleh memory://" in message


def test_production_security_config_accepts_hardened_production_values():
    _validate_production_security_config(
        app_env="production",
        debug=False,
        secret_key="prod-secret-key-with-at-least-32-characters",
        session_cookie_secure=True,
        trusted_hosts=["erp.example.com"],
        ratelimit_storage_uri="redis://127.0.0.1:6379/1",
    )


def test_default_content_security_policy_is_transitional_but_present():
    assert "default-src 'self'" in DEFAULT_CONTENT_SECURITY_POLICY
    assert "frame-ancestors 'self'" in DEFAULT_CONTENT_SECURITY_POLICY
    assert "object-src 'none'" in DEFAULT_CONTENT_SECURITY_POLICY
    assert "script-src 'self' 'unsafe-inline' https:" in DEFAULT_CONTENT_SECURITY_POLICY
