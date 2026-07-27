def test_response_gets_generated_request_id(client):
    response = client.get("/auth/login")

    request_id = response.headers.get("X-Request-ID")
    assert response.status_code == 200
    assert request_id
    assert len(request_id) == 32


def test_response_preserves_incoming_request_id(client):
    response = client.get("/auth/login", headers={"X-Request-ID": "uat-trace-123"})

    assert response.headers["X-Request-ID"] == "uat-trace-123"


def test_response_includes_content_security_policy(client):
    response = client.get("/auth/login")

    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
