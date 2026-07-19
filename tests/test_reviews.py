from sqlalchemy import func, select

from assetflow.db.models import Asset, AssetStatus, Comment
from assetflow.services.reviews import ReviewService


def test_public_review_comment_and_decision(client, db, owner):
    project_id = client.post("/api/workspaces/1/projects", headers=owner["headers"], json={"name": "Client campaign", "client_review_enabled": True}).json()["id"]
    asset_id = client.post(f"/api/projects/{project_id}/assets", headers=owner["headers"], json={"title": "Review me"}).json()["id"]
    _, token = ReviewService(db).create_link(db.get(Asset, asset_id))
    view = client.get(f"/api/public/reviews/{token}")
    assert view.status_code == 200
    comment = client.post(f"/api/public/reviews/{token}/comments", json={"name": "Client Person", "body": "Looks polished"})
    assert comment.status_code == 201
    decision = client.patch(f"/api/public/reviews/{token}/decision", json={"status": "approved"})
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"


def test_public_comment_retry_is_idempotent_and_keeps_review_state(client, db, owner):
    project_id = client.post(
        "/api/workspaces/1/projects", headers=owner["headers"], json={"name": "Client retry"}
    ).json()["id"]
    asset_id = client.post(
        f"/api/projects/{project_id}/assets", headers=owner["headers"], json={"title": "Review"}
    ).json()["id"]
    _, token = ReviewService(db).create_link(db.get(Asset, asset_id))
    headers = {"Idempotency-Key": "guest_retry_001"}

    first = client.post(
        f"/api/public/reviews/{token}/comments",
        headers=headers,
        json={"name": "Client Person", "body": "One clear note"},
    )
    retry = client.post(
        f"/api/public/reviews/{token}/comments",
        headers=headers,
        json={"name": "Client Person", "body": "One clear note"},
    )

    assert first.json()["id"] == retry.json()["id"]
    assert first.headers["x-idempotent-replay"] == "false"
    assert retry.headers["x-idempotent-replay"] == "true"
    assert db.scalar(select(func.count(Comment.id)).where(Comment.asset_id == asset_id)) == 1
    assert db.get(Asset, asset_id).status == AssetStatus.CHANGES_REQUESTED


def test_public_web_comment_retry_returns_same_thread_item(client, db, owner):
    project_id = client.post(
        "/api/workspaces/1/projects", headers=owner["headers"], json={"name": "Web retry"}
    ).json()["id"]
    asset_id = client.post(
        f"/api/projects/{project_id}/assets", headers=owner["headers"], json={"title": "Review"}
    ).json()["id"]
    _, token = ReviewService(db).create_link(db.get(Asset, asset_id))
    payload = {
        "name": "Client Person",
        "text": "Please keep this once",
        "client_request_id": "web_guest_retry_001",
    }

    first = client.post(f"/review/t/{token}/comments", data=payload)
    retry = client.post(f"/review/t/{token}/comments", data=payload)

    assert first.status_code == retry.status_code == 200
    assert first.headers["x-idempotent-replay"] == "false"
    assert retry.headers["x-idempotent-replay"] == "true"
    assert first.text.count('id="comment-') == 1
    assert retry.text.count('id="comment-') == 1
    assert db.scalar(select(func.count(Comment.id)).where(Comment.asset_id == asset_id)) == 1


def test_invalid_review_link_returns_404(client):
    response = client.get("/api/public/reviews/not-a-valid-token")
    assert response.status_code == 404


def test_guest_cannot_set_arbitrary_status(client, db, owner):
    project_id = client.post("/api/workspaces/1/projects", headers=owner["headers"], json={"name": "Review project"}).json()["id"]
    asset_id = client.post(f"/api/projects/{project_id}/assets", headers=owner["headers"], json={"title": "Asset"}).json()["id"]
    _, token = ReviewService(db).create_link(db.get(Asset, asset_id))
    response = client.patch(f"/api/public/reviews/{token}/decision", json={"status": "draft"})
    assert response.status_code == 400


def test_new_review_link_keeps_previous_link_on_same_feedback_thread(client, db, owner):
    project_id = client.post(
        "/api/workspaces/1/projects",
        headers=owner["headers"],
        json={"name": "Private review"},
    ).json()["id"]
    asset_id = client.post(
        f"/api/projects/{project_id}/assets",
        headers=owner["headers"],
        json={"title": "One continuous review"},
    ).json()["id"]
    asset = db.get(Asset, asset_id)
    first_link, first_token = ReviewService(db).create_link(asset)
    second_link, second_token = ReviewService(db).create_link(asset)
    db.refresh(first_link)

    assert first_link.is_active is True
    assert second_link.expires_at is not None
    assert client.get(f"/api/public/reviews/{first_token}").status_code == 200
    assert client.get(f"/api/public/reviews/{second_token}").status_code == 200

    comment = client.post(
        f"/api/public/reviews/{first_token}/comments",
        json={"name": "Returning client", "body": "Keep this feedback on the next link"},
    )

    assert comment.status_code == 201
    second_view = client.get(f"/review/t/{second_token}")
    assert second_view.status_code == 200
    assert "Keep this feedback on the next link" in second_view.text
