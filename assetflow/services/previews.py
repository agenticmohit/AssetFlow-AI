from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from assetflow.db.models import AssetVersion

EXPIRED_PREVIEW_URL = "/static/preview-expired.svg"


class PreviewLifecycleService:
    def __init__(self, db: Session, upload_dir: Path):
        self.db = db
        self.upload_dir = upload_dir.resolve()

    def cleanup_expired(self, now: datetime | None = None) -> int:
        now = now or datetime.utcnow()
        versions = list(
            self.db.scalars(
                select(AssetVersion).where(
                    AssetVersion.preview_delete_after.is_not(None),
                    AssetVersion.preview_delete_after <= now,
                    AssetVersion.preview_deleted_at.is_(None),
                )
            )
        )
        deleted = 0
        for version in versions:
            if version.file_url.startswith("managed://"):
                filename = version.file_url.removeprefix("managed://")
                root = self.upload_dir
            elif version.file_url.startswith("/static/uploads/"):
                filename = Path(version.file_url).name
                root = Path("static/uploads").resolve()
            else:
                continue
            target = (root / filename).resolve()
            if target.parent != root:
                continue
            target.unlink(missing_ok=True)
            version.file_url = EXPIRED_PREVIEW_URL
            version.preview_deleted_at = now
            deleted += 1
        self.db.commit()
        return deleted
