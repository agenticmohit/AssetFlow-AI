from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from assetflow.core.config import Settings, get_settings
from assetflow.core.errors import AuthenticationError
from assetflow.db.models import User
from assetflow.db.session import get_db
from assetflow.services.auth import AuthService
from assetflow.services.projects import ProjectService
from assetflow.services.reviews import ReviewService
from assetflow.services.workspaces import WorkspaceService

DB = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


def get_auth_service(db: DB, settings: Config) -> AuthService:
    return AuthService(db, settings)


def get_workspace_service(db: DB, settings: Config) -> WorkspaceService:
    return WorkspaceService(db, settings)


def get_project_service(db: DB, workspaces: Annotated[WorkspaceService, Depends(get_workspace_service)]) -> ProjectService:
    return ProjectService(db, workspaces)


def get_review_service(db: DB) -> ReviewService:
    return ReviewService(db)


def get_current_user(request: Request, authorization: str | None = Header(default=None), auth: AuthService = Depends(get_auth_service)) -> User:
    raw = request.cookies.get("assetflow_session")
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1]
    if not raw:
        raise AuthenticationError("Authentication required")
    return auth.authenticate(raw)


CurrentUser = Annotated[User, Depends(get_current_user)]

