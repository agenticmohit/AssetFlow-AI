from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from assetflow.core.errors import AppError, NotFoundError
from assetflow.core.security import new_token, token_hash
from assetflow.db.models import Asset, AssetStatus, Comment, ReviewLink
from assetflow.services.comments import CommentService


class ReviewService:
    def __init__(self, db: Session):
        self.db = db

    def create_link(self, asset: Asset) -> tuple[ReviewLink, str]:
        # Multiple secure links may point to the same asset conversation. Re-sharing
        # must not strand a client on an invalid URL or split the feedback history.
        raw, hashed = new_token()
        link = ReviewLink(
            asset_id=asset.id,
            token_hash=hashed,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        self.db.add(link)
        self.db.commit()
        return link, raw

    def resolve(self, raw: str) -> tuple[ReviewLink, Asset]:
        link = self.db.scalar(select(ReviewLink).where(ReviewLink.token_hash == token_hash(raw), ReviewLink.is_active.is_(True)))
        if not link or (link.expires_at and link.expires_at <= datetime.utcnow()):
            raise NotFoundError("Review link is invalid or expired")
        asset = self.db.get(Asset, link.asset_id)
        if not asset:
            raise NotFoundError("Asset not found")
        return link, asset

    def comment(
        self,
        raw: str,
        name: str,
        body: str,
        client_request_id: str | None = None,
    ) -> tuple[Comment, bool]:
        _, asset = self.resolve(raw)

        def mark_changes_requested() -> None:
            asset.status = AssetStatus.CHANGES_REQUESTED
            asset.approved_at = None
            for version in asset.versions:
                if not version.preview_deleted_at:
                    version.preview_delete_after = None

        return CommentService(self.db).create(
            asset_id=asset.id,
            guest_name=name,
            guest_role="client",
            body=body,
            client_request_id=client_request_id,
            before_commit=mark_changes_requested,
        )

    def decide(self, raw: str, status: AssetStatus, retention_days: int = 10) -> Asset:
        _, asset = self.resolve(raw)
        if status not in {AssetStatus.APPROVED, AssetStatus.CHANGES_REQUESTED}:
            raise AppError("Guest reviewers may only approve or request changes")
        asset.status = status
        if status == AssetStatus.APPROVED:
            asset.approved_at = datetime.utcnow()
            delete_after = asset.approved_at + timedelta(days=retention_days)
            for version in asset.versions:
                if version.file_url.startswith(("managed://", "/static/uploads/")):
                    version.preview_delete_after = delete_after
        else:
            asset.approved_at = None
            for version in asset.versions:
                if version.preview_deleted_at is None:
                    version.preview_delete_after = None
        self.db.commit()
        return asset
