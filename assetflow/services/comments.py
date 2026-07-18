import re
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from assetflow.db.models import Comment

COMMENT_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def normalize_comment_request_id(value: str | None) -> str | None:
    """Return a safe idempotency key, or None for legacy clients without one."""
    candidate = (value or "").strip()
    return candidate if COMMENT_REQUEST_ID_PATTERN.fullmatch(candidate) else None


class CommentService:
    """Create comments exactly once, including across concurrent retries."""

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        asset_id: int,
        body: str,
        client_request_id: str | None,
        author_id: int | None = None,
        guest_name: str | None = None,
        guest_role: str | None = None,
        parent_id: int | None = None,
        before_commit: Callable[[], None] | None = None,
    ) -> tuple[Comment, bool]:
        request_id = normalize_comment_request_id(client_request_id)
        existing = self._find(asset_id, request_id)
        if existing:
            return existing, False

        comment = Comment(
            asset_id=asset_id,
            author_id=author_id,
            guest_name=guest_name,
            guest_role=guest_role,
            body=body,
            parent_id=parent_id,
            client_request_id=request_id,
        )
        self.db.add(comment)
        if before_commit:
            before_commit()
        try:
            self.db.commit()
        except IntegrityError:
            # Two retries can race after an ambiguous timeout. The database
            # constraint chooses the winner; the loser returns that same row.
            self.db.rollback()
            existing = self._find(asset_id, request_id)
            if existing:
                return existing, False
            raise
        self.db.refresh(comment)
        return comment, True

    def _find(self, asset_id: int, request_id: str | None) -> Comment | None:
        if not request_id:
            return None
        return self.db.scalar(
            select(Comment).where(
                Comment.asset_id == asset_id,
                Comment.client_request_id == request_id,
            )
        )
