import re
from datetime import datetime, timedelta

from sqlalchemy import select

from assetflow.db.models import (
    Asset,
    AssetStatus,
    AssetVersion,
    Comment,
    RevisionTask,
    Role,
    WorkspaceMember,
)
from assetflow.services.previews import EXPIRED_PREVIEW_URL, PreviewLifecycleService


def create_owner(client):
    response = client.post(
        "/api/auth/signup",
        json={
            "email": "beta-owner@example.com",
            "name": "Beta Owner",
            "password": "strong-password",
            "workspace_name": "Beta Studio",
        },
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_project(client, headers):
    response = client.post(
        "/api/workspaces/1/projects",
        headers=headers,
        json={"name": "Launch campaign", "client_name": "Norr Studio"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_navigation_and_complete_review_loop(client, db, settings):
    headers = create_owner(client)
    project_id = create_project(client, headers)

    for path, label in [
        ("/", "Overview"),
        ("/projects", "Projects"),
        ("/assets", "All assets"),
        ("/approvals", "Approvals"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert label in response.text

    upload = client.post(
        "/assets",
        data={
            "project_id": str(project_id),
            "title": "Launch poster",
            "asset_type": "Instagram post",
            "notes": "Review the hierarchy",
        },
        files={"file": ("launch.png", b"temporary-preview", "image/png")},
        follow_redirects=False,
    )
    assert upload.status_code == 303
    asset_id = int(upload.headers["location"].rsplit("/", 1)[1])
    uploaded_version = db.scalar(select(AssetVersion).where(AssetVersion.asset_id == asset_id))
    media_path = f"/media/versions/{uploaded_version.id}"
    assert uploaded_version.file_url.startswith("managed://")
    assert client.get(media_path).status_code == 200
    assert client.get(
        f"/static/uploads/{uploaded_version.file_url.removeprefix('managed://')}"
    ).status_code == 404

    task = client.post(f"/assets/{asset_id}/tasks", data={"text": "Increase logo spacing"})
    assert task.status_code == 200
    task_id = db.scalar(select(RevisionTask.id).where(RevisionTask.asset_id == asset_id))
    toggled = client.post(f"/tasks/{task_id}/toggle")
    assert toggled.status_code == 200
    assert db.get(RevisionTask, task_id).is_done is True

    link = client.post(f"/assets/{asset_id}/review-links")
    assert link.status_code == 200
    review_url = re.search(r'value="([^"]+/review/t/[^"]+)"', link.text).group(1)
    review_path = review_url.removeprefix("http://testserver")
    review_page = client.get(review_path)
    assert review_page.status_code == 200
    assert media_path in review_page.text
    assert f"{media_path}?token=" not in review_page.text
    assert client.cookies.get("assetflow_review")
    client.cookies.delete("assetflow_session")
    assert client.get(media_path).status_code == 200

    guest_comment = client.post(
        f"{review_path}/comments",
        data={"name": "Client Reviewer", "text": "Love this direction ✨"},
    )
    assert guest_comment.status_code == 200
    assert "Changes Requested" in guest_comment.text
    assert db.get(Asset, asset_id).status == AssetStatus.CHANGES_REQUESTED
    decision = client.post(f"{review_path}/decision", data={"status": "approved"})
    assert decision.status_code == 200

    asset = db.get(Asset, asset_id)
    version = db.scalar(select(AssetVersion).where(AssetVersion.asset_id == asset_id))
    assert asset.approved_at is not None
    assert version.preview_delete_after - asset.approved_at == timedelta(days=10)
    assert db.scalar(select(Comment).where(Comment.asset_id == asset_id)).body == "Love this direction ✨"

    preview_path = settings.upload_dir / version.file_url.rsplit("/", 1)[1]
    assert preview_path.exists()
    deleted = PreviewLifecycleService(db, settings.upload_dir).cleanup_expired(
        version.preview_delete_after + timedelta(seconds=1)
    )
    assert deleted == 1
    assert not preview_path.exists()
    assert version.file_url == EXPIRED_PREVIEW_URL
    assert db.get(Asset, asset_id).title == "Launch poster"
    assert db.scalar(select(Comment).where(Comment.asset_id == asset_id)) is not None


def test_team_invitation_joins_existing_workspace(client, db):
    create_owner(client)
    invitation = client.post(
        "/team/invite",
        data={"email": "designer-invite@example.com", "role": "designer"},
    )
    assert invitation.status_code == 200
    signup_url = re.search(r'value="([^"]+/signup\?invite=[^"]+)"', invitation.text).group(1)
    signup_path = signup_url.removeprefix("http://testserver")
    signup_page = client.get(signup_path)
    assert "Join Beta Studio" in signup_page.text

    token = signup_path.split("invite=", 1)[1]
    accepted = client.post(
        "/signup",
        data={
            "invite_token": token,
            "workspace_name": "Beta Studio",
            "email": "designer-invite@example.com",
            "name": "Invited Designer",
            "password": "strong-password",
        },
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    membership = db.scalar(
        select(WorkspaceMember).where(WorkspaceMember.user_id == 2)
    )
    assert membership.workspace_id == 1
    assert membership.role == Role.DESIGNER


def test_cleanup_skips_non_managed_urls(db, tmp_path):
    # Externally hosted/source links are references, not files owned by AssetFlow.
    from assetflow.core.security import hash_password
    from assetflow.db.models import Project, User, Workspace

    user = User(email="cleanup@example.com", name="Cleanup", password_hash=hash_password("strong-password"))
    workspace = Workspace(name="Cleanup", slug="cleanup")
    db.add_all([user, workspace])
    db.flush()
    project = Project(workspace_id=workspace.id, name="External")
    db.add(project)
    db.flush()
    asset = Asset(project_id=project.id, title="Drive reference", assigned_designer_id=user.id)
    db.add(asset)
    db.flush()
    version = AssetVersion(
        asset_id=asset.id,
        number=1,
        file_url="https://drive.example/design.png",
        uploaded_by_id=user.id,
        preview_delete_after=datetime.utcnow() - timedelta(days=1),
    )
    db.add(version)
    db.commit()

    assert PreviewLifecycleService(db, tmp_path).cleanup_expired() == 0
    assert version.file_url.startswith("https://drive.example")
