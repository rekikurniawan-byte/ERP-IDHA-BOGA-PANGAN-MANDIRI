"""Shared test fixtures for PT Idha Boga Pangan Mandiri."""
import os
from urllib.parse import urlparse

import pytest


ACTIVE_ERP_DATABASES = {"idha_boga", "idha_boga_staging", "idha_boga_development", "idha_boga_dev"}
DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://localhost/test_db"


def _force_test_database_url():
    """Keep pytest from seeding QA data into the active development database."""
    active_url = os.environ.get("DATABASE_URL", "")
    active_db = (urlparse(active_url).path or "").lstrip("/")
    test_url = os.environ.get("PYTEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)

    if active_db in ACTIVE_ERP_DATABASES and os.environ.get("ALLOW_PYTEST_ON_ACTIVE_ERP_DB") != "1":
        os.environ["DATABASE_URL"] = test_url
    else:
        os.environ.setdefault("DATABASE_URL", test_url)

    os.environ["APP_ENV"] = "testing"
    os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")


_force_test_database_url()


@pytest.fixture
def app():
    """Create application for testing."""
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()
