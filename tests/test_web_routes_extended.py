from pathlib import Path

from sqlalchemy import func, select

from assetflow.core.security import hash_password
from assetflow.db.models import (
    Asset,
    AssetStatus,
    AssetVersion,
    Comment,
    Project,
    ReviewLink,
    Role,
    User,
    WorkspaceMember,
)
from assetflow.db.seed import seed_demo
from assetflow.services.reviews import ReviewService


def web_owner(client):
    response = client.post(
        "/api/auth/signup",
        json={
            "email": "web-owner@example.com",
            "name": "Web Owner",
            "password": "strong-password",
            "workspace_name": "Web Studio",
        },
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_project_and_asset_forms_are_operational(client, db, settings):
    web_owner(client)
    assert client.get("/projects/new").status_code == 200
    created = client.post(
        "/projects",
        data={"name": "Editorial launch", "client_name": "Acme", "description": "A launch system"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    project_id = int(created.headers["location"].rsplit("/", 1)[1])
    assert "Editorial launch" in client.get(f"/projects/{project_id}").text
    assert client.get(f"/assets/new?project_id={project_id}").status_code == 200

    created_asset = client.post(
        "/assets",
        data={"project_id": project_id, "title": "Editorial tile", "asset_type": "Carousel"},
        files={"file": ("tile.webp", b"webp-preview", "image/webp")},
        follow_redirects=False,
    )
    assert created_asset.status_code == 303
    asset_id = int(created_asset.headers["location"].rsplit("/", 1)[1])
    asset_page = client.get(f"/assets/{asset_id}")
    assert "Editorial tile" in asset_page.text
    assert "Share for review" in asset_page.text
    assert "Send this design for review" in asset_page.text
    assert "Share without signup" not in asset_page.text
    assert "Editorial tile" in client.get("/assets?q=Editorial").text
    assert "Editorial tile" in client.get("/assets?status=in_review").text

    first = client.post(f"/assets/{asset_id}/comments", data={"text": "Try a warmer crop"})
    assert first.status_code == 200
    assert "Ready for Review" in first.text
    assert db.get(Asset, asset_id).status == AssetStatus.IN_REVIEW
    parent_id = db.scalar(select(Comment.id).where(Comment.asset_id == asset_id))
    reply = client.post(
        f"/assets/{asset_id}/comments",
        data={"text": "I will test it 🎨", "parent_id": str(parent_id)},
    )
    assert "Reply in thread" in reply.text

    revision = client.post(
        f"/assets/{asset_id}/versions",
        data={"notes": "Warmer crop"},
        files={"file": ("tile-v2.jpg", b"jpg-preview", "image/jpeg")},
        follow_redirects=False,
    )
    assert revision.status_code == 303
    assert db.scalar(select(func.count(AssetVersion.id)).where(AssetVersion.asset_id == asset_id)) == 2
    changes = client.post(f"/assets/{asset_id}/status", data={"status": "changes requested"})
    assert changes.status_code == 403
    approved = client.post(f"/assets/{asset_id}/status", data={"status": "approved"})
    assert approved.status_code == 403
    later = client.post(f"/assets/{asset_id}/designer-action", data={"action": "later"})
    assert later.status_code == 422
    done = client.post(f"/assets/{asset_id}/designer-action", data={"action": "done"})
    assert "Completed" in done.text
    assert "Mark done" not in done.text
    assert db.get(Asset, asset_id).status == AssetStatus.FINAL_DELIVERED

    latest_version = db.scalar(
        select(AssetVersion)
        .where(AssetVersion.asset_id == asset_id)
        .order_by(AssetVersion.number.desc())
    )
    managed_file = Path(settings.upload_dir) / latest_version.file_url.removeprefix("managed://")
    assert managed_file.is_file()
    ReviewService(db).create_link(db.get(Asset, asset_id))

    deleted = client.post(f"/assets/{asset_id}/delete", follow_redirects=False)
    assert deleted.status_code == 303
    assert deleted.headers["location"] == f"/projects/{project_id}"
    assert db.get(Asset, asset_id) is None
    assert db.scalar(select(func.count(ReviewLink.id)).where(ReviewLink.asset_id == asset_id)) == 0
    assert not managed_file.exists()


def test_project_page_management_and_cascade_delete(client, db, settings):
    web_owner(client)
    created = client.post(
        "/projects",
        data={"name": "Campaign to remove", "client_name": "Acme"},
        follow_redirects=False,
    )
    project_id = int(created.headers["location"].rsplit("/", 1)[1])
    created_asset = client.post(
        "/assets",
        data={"project_id": project_id, "title": "Wrong export", "asset_type": "Poster"},
        files={"file": ("wrong-export.png", b"managed-preview", "image/png")},
        follow_redirects=False,
    )
    asset_id = int(created_asset.headers["location"].rsplit("/", 1)[1])
    version = db.scalar(select(AssetVersion).where(AssetVersion.asset_id == asset_id))
    managed_file = Path(settings.upload_dir) / version.file_url.removeprefix("managed://")
    assert managed_file.is_file()
    ReviewService(db).create_link(db.get(Asset, asset_id))

    page = client.get(f"/projects/{project_id}")
    assert page.status_code == 200
    assert "Delete project" in page.text
    assert "Delete Wrong export" in page.text
    assert "Keep design" in page.text

    deleted = client.post(f"/projects/{project_id}/delete", follow_redirects=False)
    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/projects"
    db.expire_all()
    assert db.get(Project, project_id) is None
    assert db.get(Asset, asset_id) is None
    assert db.scalar(select(func.count(ReviewLink.id)).where(ReviewLink.asset_id == asset_id)) == 0
    assert not managed_file.exists()


def test_upload_validation_and_not_found_paths(client, settings):
    headers = web_owner(client)
    project_id = client.post(
        "/api/workspaces/1/projects", headers=headers, json={"name": "Validation"}
    ).json()["id"]
    unsupported = client.post(
        "/assets",
        data={"project_id": project_id, "title": "Bad file"},
        files={"file": ("bad.exe", b"bad", "application/octet-stream")},
    )
    assert unsupported.status_code == 415
    missing_file = client.post(
        "/assets", data={"project_id": project_id, "title": "No file"}
    )
    assert missing_file.status_code == 422
    wrong_project = client.post(
        "/assets",
        data={"project_id": 999, "title": "Wrong project"},
        files={"file": ("ok.png", b"png", "image/png")},
    )
    assert wrong_project.status_code == 404
    assert client.get("/projects/999").status_code == 404
    assert client.get("/assets/999").status_code == 404
    assert client.post("/tasks/999/toggle").status_code == 404
    assert client.post("/assets/999/review-links").status_code == 404

    settings.max_upload_bytes = 3
    too_large = client.post(
        "/assets",
        data={"project_id": project_id, "title": "Too large"},
        files={"file": ("large.png", b"more-than-three", "image/png")},
    )
    assert too_large.status_code == 413


def test_designer_view_and_web_permissions(client, db):
    owner_headers = web_owner(client)
    project_id = client.post(
        "/api/workspaces/1/projects", headers=owner_headers, json={"name": "Team work"}
    ).json()["id"]
    designer = User(
        email="web-designer@example.com",
        name="Web Designer",
        password_hash=hash_password("strong-password"),
    )
    db.add(designer)
    db.flush()
    db.add(WorkspaceMember(workspace_id=1, user_id=designer.id, role=Role.DESIGNER))
    db.commit()
    assigned = client.post(
        f"/api/projects/{project_id}/assets",
        headers=owner_headers,
        json={"title": "Assigned design", "assigned_designer_id": designer.id},
    ).json()
    client.post(
        "/login",
        data={"email": designer.email, "password": "strong-password"},
        follow_redirects=False,
    )
    assert client.get("/projects/new").status_code == 403
    assert client.post("/projects", data={"name": "Forbidden"}).status_code == 403
    assert client.get("/team/invite").status_code == 403
    assert client.post(f"/assets/{assigned['id']}/status", data={"status": "approved"}).status_code == 403
    assert "Assigned design" in client.get("/").text


def test_public_review_invalid_and_change_request(client, db):
    headers = web_owner(client)
    project_id = client.post(
        "/api/workspaces/1/projects", headers=headers, json={"name": "Review"}
    ).json()["id"]
    asset_id = client.post(
        f"/api/projects/{project_id}/assets",
        headers=headers,
        json={"title": "Public tile"},
    ).json()["id"]
    _, token = ReviewService(db).create_link(db.get(Asset, asset_id))
    assert client.get("/review/t/not-valid").status_code == 200
    assert "no longer available" in client.get("/review/t/not-valid").text
    decision = client.post(
        f"/review/t/{token}/decision", data={"status": "changes_requested"}
    )
    assert decision.status_code == 200
    assert db.get(Asset, asset_id).status == AssetStatus.CHANGES_REQUESTED
    invalid = client.post(f"/review/t/{token}/decision", data={"status": "draft"})
    assert invalid.status_code == 422
    assert client.post(
        "/review/t/not-valid/comments", data={"name": "Client", "text": "Hello"}
    ).status_code == 404


def test_change_request_forms_create_feedback_and_status(client, db):
    headers = web_owner(client)
    project_id = client.post(
        "/api/workspaces/1/projects", headers=headers, json={"name": "Revision flow"}
    ).json()["id"]
    asset_id = client.post(
        f"/api/projects/{project_id}/assets",
        headers=headers,
        json={"title": "Revision poster"},
    ).json()["id"]
    page = client.get(f"/assets/{asset_id}")
    assert "Mark done" in page.text
    assert "Generate from feedback" in page.text
    assert "Approve" not in page.text
    internal = client.post(
        f"/assets/{asset_id}/change-request",
        data={"text": "Increase the headline contrast"},
        follow_redirects=False,
    )
    assert internal.status_code == 403
    assert db.get(Asset, asset_id).status == AssetStatus.DRAFT

    client.post(f"/assets/{asset_id}/comments", data={"text": "Designer context note"})

    _, token = ReviewService(db).create_link(db.get(Asset, asset_id))
    review_page = client.get(f"/review/t/{token}")
    assert "Designer" in review_page.text
    assert "Studio owner" not in review_page.text
    public = client.post(
        f"/review/t/{token}/change-request",
        data={"name": "Client Reviewer", "text": "Use the warmer brand colour"},
        follow_redirects=False,
    )
    assert public.status_code == 303
    assert db.scalar(select(func.count(Comment.id)).where(Comment.asset_id == asset_id)) == 2
    generated = client.post(f"/assets/{asset_id}/ai/tasks")
    assert generated.status_code == 200
    assert "warmer brand colour" in generated.text.lower()


def test_demo_seed_is_idempotent(db):
    seed_demo(db)
    assert db.scalar(select(func.count(User.id))) == 2
    assert db.scalar(select(func.count(Project.id))) == 6
    assert db.scalar(select(func.count(Asset.id))) == 6
    seed_demo(db)
    assert db.scalar(select(func.count(User.id))) == 2
