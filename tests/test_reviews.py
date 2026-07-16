from assetflow.db.models import Asset
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


def test_invalid_review_link_returns_404(client):
    response = client.get("/api/public/reviews/not-a-valid-token")
    assert response.status_code == 404


def test_guest_cannot_set_arbitrary_status(client, db, owner):
    project_id = client.post("/api/workspaces/1/projects", headers=owner["headers"], json={"name": "Review project"}).json()["id"]
    asset_id = client.post(f"/api/projects/{project_id}/assets", headers=owner["headers"], json={"title": "Asset"}).json()["id"]
    _, token = ReviewService(db).create_link(db.get(Asset, asset_id))
    response = client.patch(f"/api/public/reviews/{token}/decision", json={"status": "draft"})
    assert response.status_code == 400


def test_new_review_link_revokes_the_previous_link(client, db, owner):
    project_id = client.post(
        "/api/workspaces/1/projects",
        headers=owner["headers"],
        json={"name": "Private review"},
    ).json()["id"]
    asset_id = client.post(
        f"/api/projects/{project_id}/assets",
        headers=owner["headers"],
        json={"title": "Only latest link works"},
    ).json()["id"]
    asset = db.get(Asset, asset_id)
    first_link, first_token = ReviewService(db).create_link(asset)
    second_link, second_token = ReviewService(db).create_link(asset)
    db.refresh(first_link)

    assert first_link.is_active is False
    assert second_link.expires_at is not None
    assert client.get(f"/api/public/reviews/{first_token}").status_code == 404
    assert client.get(f"/api/public/reviews/{second_token}").status_code == 200
