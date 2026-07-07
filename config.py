import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name, default=""):
    value = os.getenv(name, default)
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _normalize_database_url(value):
    """Normalize PostgreSQL DATABASE_URL for SQLAlchemy 2 / psycopg.

    POSTGRES-ONLY LOCK: SQLite fallback/local mode is intentionally removed.
    """
    if not value:
        return value
    value = value.strip()
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://"):]
    if value.startswith("postgresql://") and "+" not in value.split(":", 1)[0]:
        return "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


def _require_postgres_database_url():
    raw_url = os.getenv("DATABASE_URL")
    database_url = _normalize_database_url(raw_url)
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL wajib diset dan harus PostgreSQL. "
            "Contoh: postgresql+psycopg://user:password@localhost:5432/idha_boga_staging"
        )
    driver = database_url.split(":", 1)[0].lower()
    if not (driver.startswith("postgresql") or driver.startswith("postgres")):
        raise RuntimeError(
            "POSTGRES-ONLY LOCK aktif: DATABASE_URL harus PostgreSQL. "
            "SQLite/local file database tidak didukung lagi."
        )
    return database_url


def _get_secret_key():
    secret_key = os.getenv("SECRET_KEY")
    app_env = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "production")).strip().lower()

    if secret_key:
        return secret_key

    if app_env in {"dev", "development", "local"}:
        return "dev-only-change-this-secret-key"

    raise RuntimeError(
        "SECRET_KEY belum diset. Untuk production, set environment variable SECRET_KEY "
        "dengan nilai acak yang kuat sebelum menjalankan aplikasi."
    )


class Config:
    APP_ENV = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "production")).strip().lower()
    APP_VERSION = os.getenv("APP_VERSION", "POSTGRES_ONLY_PRODUCTION")
    DEBUG = _env_bool("APP_DEBUG", _env_bool("FLASK_DEBUG", False))
    SECRET_KEY = _get_secret_key()

    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    INSTANCE_DIR = os.path.join(BASE_DIR, "instance")

    DATABASE_URL = _require_postgres_database_url()
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    IS_PRODUCTION = APP_ENV in {"production", "prod"}
    PREFERRED_URL_SCHEME = "https" if IS_PRODUCTION else "http"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    PERMANENT_SESSION_LIFETIME = timedelta(seconds=int(os.getenv("PERMANENT_SESSION_LIFETIME", "86400")))
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = SESSION_COOKIE_SAMESITE
    TRUSTED_HOSTS = _csv_env("TRUSTED_HOSTS", os.getenv("APP_TRUSTED_HOSTS", "")) or None
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "5 per minute")

    UPLOAD_ROOT = os.getenv("UPLOAD_ROOT", os.path.join(INSTANCE_DIR, "uploads"))
    DIGITAL_ATTACHMENT_UPLOAD_DIR = os.getenv(
        "DIGITAL_ATTACHMENT_UPLOAD_DIR",
        os.path.join(UPLOAD_ROOT, "digital_attachments")
    )
    DIGITAL_ATTACHMENT_MAX_BYTES = int(os.getenv("DIGITAL_ATTACHMENT_MAX_BYTES", str(5 * 1024 * 1024)))
    DIGITAL_ATTACHMENT_ALLOWED_EXTENSIONS = os.getenv("DIGITAL_ATTACHMENT_ALLOWED_EXTENSIONS", "jpg,jpeg,png,webp,pdf")

    BACKUP_ROOT = os.getenv("BACKUP_ROOT", os.path.join(INSTANCE_DIR, "backups"))
    BACKUP_STORAGE_DIR = os.getenv("BACKUP_STORAGE_DIR", BACKUP_ROOT)

    LOG_ROOT = os.getenv("LOG_ROOT", os.path.join(INSTANCE_DIR, "logs"))
    APP_LOG_FILE = os.getenv("APP_LOG_FILE", os.path.join(LOG_ROOT, "app.log"))
    ERROR_LOG_FILE = os.getenv("ERROR_LOG_FILE", os.path.join(LOG_ROOT, "error.log"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))
    LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "10"))
    HEALTH_DISK_MIN_FREE_BYTES = int(os.getenv("HEALTH_DISK_MIN_FREE_BYTES", str(1024 * 1024 * 1024)))
    HEALTH_REQUIRE_VERIFIED_BACKUP = _env_bool("HEALTH_REQUIRE_VERIFIED_BACKUP", False)
    HEALTH_REQUIRE_POSTGRES_IN_PRODUCTION = True
    PROXY_HEADERS_ENABLED = _env_bool("PROXY_HEADERS_ENABLED", IS_PRODUCTION)
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(DIGITAL_ATTACHMENT_MAX_BYTES)))
