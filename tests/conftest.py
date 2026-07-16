import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from assetflow.core.config import Settings, get_settings
from assetflow.db.base import Base
from assetflow.db.session import get_db
from assetflow.main import create_app


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, environment="test", debug=True, database_url="sqlite://", secret_key="test-secret", upload_dir=tmp_path / "uploads", openai_api_key=None)


@pytest.fixture
def client(db, settings):
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def owner(client):
    response = client.post("/api/auth/signup", json={"email": "owner@example.com", "name": "Studio Owner", "password": "strong-password", "workspace_name": "Studio North"})
    assert response.status_code == 201
    return {"token": response.json()["access_token"], "headers": {"Authorization": f"Bearer {response.json()['access_token']}"}, "workspace_id": 1}

