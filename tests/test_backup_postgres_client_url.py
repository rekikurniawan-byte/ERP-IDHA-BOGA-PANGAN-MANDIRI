from app.services.backup_service import _postgres_client_url


def test_postgres_client_url_removes_sqlalchemy_driver_suffix():
    assert _postgres_client_url("postgresql+psycopg://user:pass@localhost/db") == "postgresql://user:pass@localhost/db"
    assert _postgres_client_url("postgresql+psycopg2://user:pass@localhost/db") == "postgresql://user:pass@localhost/db"
    assert _postgres_client_url("postgresql://user:pass@localhost/db") == "postgresql://user:pass@localhost/db"
