from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from assetflow.core.config import get_settings


def build_engine(database_url: str):
    options = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    pool_options = {} if database_url.startswith("sqlite") else {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_recycle": 1800,
        "pool_timeout": 30,
    }
    return create_engine(
        database_url,
        connect_args=options,
        pool_pre_ping=True,
        **pool_options,
    )


engine = build_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
