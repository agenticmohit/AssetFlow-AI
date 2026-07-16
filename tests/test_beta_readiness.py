import pytest
from pydantic import ValidationError

from assetflow.core.config import Settings
from assetflow.main import create_app


def signup(client, email: str, workspace: str):
    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "name": email.split("@")[0].title(),
            "password": "strong-password",
            "workspace_name": workspace,
        },
    )
    return response.json()["access_token"]


def test_production_configuration_requires_strong_secret():
    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key="weak")
    settings = Settings(
        environment="production",
        secret_key="x" * 40,
        debug=False,
        database_url="postgresql+psycopg://user:pass@db.example/assetflow",
        allowed_hosts=["app.example.com"],
    )
    assert settings.secure_cookies is True


def test_production_configuration_rejects_local_infrastructure():
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            secret_key="x" * 40,
            database_url="sqlite:///production.db",
            allowed_hosts=["app.example.com"],
        )
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            secret_key="x" * 40,
            database_url="postgresql+psycopg://user:pass@db.example/assetflow",
            allowed_hosts=["localhost"],
        )


def test_jwt_algorithm_is_restricted_to_audited_hs256():
    with pytest.raises(ValidationError):
        Settings(environment="test", jwt_algorithm="ES256")


def test_dashboard_is_tenant_scoped(client):
    first_token = signup(client, "first@example.com", "First Studio")
    first_headers = {"Authorization": f"Bearer {first_token}"}
    first_project = client.post(
        "/api/workspaces/1/projects", headers=first_headers, json={"name": "First project"}
    ).json()
    client.post(
        f"/api/projects/{first_project['id']}/assets",
        headers=first_headers,
        json={"title": "First private poster"},
    )

    second_token = signup(client, "second@example.com", "Second Studio")
    second_headers = {"Authorization": f"Bearer {second_token}"}
    second_project = client.post(
        "/api/workspaces/2/projects", headers=second_headers, json={"name": "Second project"}
    ).json()
    client.post(
        f"/api/projects/{second_project['id']}/assets",
        headers=second_headers,
        json={"title": "Second private poster"},
    )

    client.cookies.set("assetflow_session", first_token)
    first_dashboard = client.get("/")
    assert "First private poster" in first_dashboard.text
    assert "Second private poster" not in first_dashboard.text

    client.cookies.set("assetflow_session", second_token)
    second_dashboard = client.get("/")
    assert "Second private poster" in second_dashboard.text
    assert "First private poster" not in second_dashboard.text


def test_cross_site_cookie_write_is_blocked(client):
    signup(client, "origin@example.com", "Origin Studio")
    response = client.post(
        "/logout",
        headers={"Origin": "https://attacker.example"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_origin"


def test_browser_responses_include_security_and_privacy_headers(client):
    response = client.get("/login")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_production_hides_interactive_api_docs(tmp_path):
    settings = Settings(
        environment="production",
        secret_key="x" * 40,
        database_url="postgresql+psycopg://user:pass@db.example/assetflow",
        allowed_hosts=["app.example.com"],
        upload_dir=tmp_path / "uploads",
    )
    app = create_app(settings)
    assert app.docs_url is None
    assert app.openapi_url is None
