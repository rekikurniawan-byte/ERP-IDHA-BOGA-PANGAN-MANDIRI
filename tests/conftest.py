"""Shared test fixtures for PT Idha Boga Pangan Mandiri."""
import pytest


@pytest.fixture
def app():
    """Create application for testing."""
    import os
    os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://localhost/test_db")
    os.environ.setdefault("APP_ENV", "testing")

    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()
