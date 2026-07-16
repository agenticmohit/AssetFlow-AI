from assetflow.core.config import get_settings
from assetflow.db.session import SessionLocal
from assetflow.services.previews import PreviewLifecycleService


def main() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        count = PreviewLifecycleService(db, settings.upload_dir).cleanup_expired()
    print(f"Deleted {count} expired review preview(s).")


if __name__ == "__main__":
    main()

