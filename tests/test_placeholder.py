"""Basic startup regression tests."""


def test_flask_app_factory_builds_route_map():
    """Verify the app factory registers the expected core route map."""
    from app import create_app

    app = create_app()
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}

    assert "auth.login" in endpoints
    assert "dashboard.index" in endpoints
    assert "finance.generate_period_invoice_preview" in endpoints


def test_import_app():
    """Verify the Flask app can be imported without error."""
    from app import create_app
    assert create_app is not None
