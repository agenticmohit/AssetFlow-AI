from sqlalchemy import select

from assetflow.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from assetflow.db.models import Workspace


def test_password_hash_round_trip():
    encoded = hash_password("correct horse battery staple")
    assert encoded != "correct horse battery staple"
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password("wrong", "broken-hash")


def test_jwt_access_token_round_trip_and_rejects_tampering():
    token = create_access_token(42, "test-secret", "HS256", 5)
    assert decode_access_token(token, "test-secret", "HS256") == 42
    assert decode_access_token(token + "tampered", "test-secret", "HS256") is None
    assert decode_access_token(token, "wrong-secret", "HS256") is None


def test_signup_login_and_duplicate(client):
    payload = {"email": "hello@example.com", "name": "Demo Designer", "password": "long-password", "workspace_name": "Demo Studio"}
    signup = client.post("/api/auth/signup", json=payload)
    assert signup.status_code == 201
    assert signup.json()["token_type"] == "bearer"
    assert "httponly" in signup.headers["set-cookie"].lower()
    duplicate = client.post("/api/auth/signup", json=payload)
    assert duplicate.status_code == 409
    login = client.post("/api/auth/login", json={"email": payload["email"], "password": payload["password"]})
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_signup_workspace_name_is_optional(client, db):
    omitted = client.post(
        "/api/auth/signup",
        json={
            "email": "solo@example.com",
            "name": "Solo Designer",
            "password": "long-password",
        },
    )
    blank = client.post(
        "/api/auth/signup",
        json={
            "email": "freelancer@example.com",
            "name": "Freelance Designer",
            "password": "long-password",
            "workspace_name": "   ",
        },
    )

    assert omitted.status_code == 201
    assert blank.status_code == 201
    workspaces = list(db.scalars(select(Workspace).order_by(Workspace.id)))
    assert [workspace.name for workspace in workspaces] == [
        "Personal workspace",
        "Personal workspace",
    ]
    assert workspaces[0].slug == "personal-workspace"
    assert workspaces[1].slug == "personal-workspace-2"


def test_login_rejects_invalid_credentials(client):
    response = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "incorrect"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_protected_endpoint_requires_auth(client):
    response = client.get("/api/workspaces/1/projects")
    assert response.status_code == 401
