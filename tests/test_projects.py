from sqlalchemy import func, select

from assetflow.core.security import hash_password
from assetflow.db.models import Comment, Role, User, WorkspaceMember


def test_owner_creates_project_and_asset(client, owner):
    project = client.post("/api/workspaces/1/projects", headers=owner["headers"], json={"name": "New campaign", "client_name": "Serein", "client_review_enabled": True})
    assert project.status_code == 201
    assert project.json()["client_name"] == "Serein"
    asset = client.post(f"/api/projects/{project.json()['id']}/assets", headers=owner["headers"], json={"title": "Launch poster", "asset_type": "Instagram post"})
    assert asset.status_code == 201
    assert asset.json()["status"] == "draft"
    listed = client.get("/api/workspaces/1/projects", headers=owner["headers"])
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["New campaign"]


def test_comment_and_status_workflow(client, owner):
    project_id = client.post("/api/workspaces/1/projects", headers=owner["headers"], json={"name": "Campaign"}).json()["id"]
    asset_id = client.post(f"/api/projects/{project_id}/assets", headers=owner["headers"], json={"title": "Poster"}).json()["id"]
    comment = client.post(f"/api/assets/{asset_id}/comments", headers=owner["headers"], json={"body": "Make it more editorial"})
    assert comment.status_code == 201
    updated = client.patch(f"/api/assets/{asset_id}/status", headers=owner["headers"], json={"status": "approved"})
    assert updated.status_code == 403
    assert updated.json()["error"]["message"] == "Only clients can make review decisions"


def test_comment_retry_with_same_idempotency_key_is_created_once(client, db, owner):
    project_id = client.post(
        "/api/workspaces/1/projects", headers=owner["headers"], json={"name": "Retry safe"}
    ).json()["id"]
    asset_id = client.post(
        f"/api/projects/{project_id}/assets",
        headers=owner["headers"],
        json={"title": "Poster"},
    ).json()["id"]
    headers = {**owner["headers"], "Idempotency-Key": "comment_retry_001"}

    first = client.post(
        f"/api/assets/{asset_id}/comments", headers=headers, json={"body": "Keep this once"}
    )
    retry = client.post(
        f"/api/assets/{asset_id}/comments", headers=headers, json={"body": "Keep this once"}
    )

    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    assert first.headers["x-idempotent-replay"] == "false"
    assert retry.headers["x-idempotent-replay"] == "true"
    assert db.scalar(select(func.count(Comment.id)).where(Comment.asset_id == asset_id)) == 1


def test_designer_cannot_create_project_or_approve(client, db, owner):
    user = User(email="designer2@example.com", name="Designer", password_hash=hash_password("designer-password"))
    db.add(user)
    db.flush()
    db.add(WorkspaceMember(workspace_id=1, user_id=user.id, role=Role.DESIGNER))
    db.commit()
    login = client.post("/api/auth/login", json={"email": user.email, "password": "designer-password"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    forbidden = client.post("/api/workspaces/1/projects", headers=headers, json={"name": "Not allowed"})
    assert forbidden.status_code == 403
    project_id = client.post("/api/workspaces/1/projects", headers=owner["headers"], json={"name": "Assigned"}).json()["id"]
    asset_id = client.post(f"/api/projects/{project_id}/assets", headers=owner["headers"], json={"title": "Assigned poster", "assigned_designer_id": user.id}).json()["id"]
    approve = client.patch(f"/api/assets/{asset_id}/status", headers=headers, json={"status": "approved"})
    assert approve.status_code == 403


def test_owner_can_invite_team_member(client, owner):
    result = client.post("/api/workspaces/1/invites", headers=owner["headers"], json={"email": "designer@example.com", "role": "designer"})
    assert result.status_code == 201
    assert result.json()["invite_token"]
