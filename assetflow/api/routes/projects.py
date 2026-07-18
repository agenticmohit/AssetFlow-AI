from fastapi import APIRouter, Depends, Header, Response, status

from assetflow.api.dependencies import CurrentUser, get_project_service, get_workspace_service
from assetflow.schemas.projects import (
    AssetCreate,
    AssetRead,
    CommentCreate,
    InviteCreate,
    ProjectCreate,
    ProjectRead,
    StatusUpdate,
)
from assetflow.services.projects import ProjectService
from assetflow.services.workspaces import WorkspaceService

router = APIRouter(tags=["workspaces"])


@router.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectRead])
def list_projects(workspace_id: int, user: CurrentUser, service: ProjectService = Depends(get_project_service)):
    return service.list_projects(workspace_id, user)


@router.post("/workspaces/{workspace_id}/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(workspace_id: int, data: ProjectCreate, user: CurrentUser, service: ProjectService = Depends(get_project_service)):
    return service.create_project(workspace_id, user, data)


@router.post("/workspaces/{workspace_id}/invites", status_code=status.HTTP_201_CREATED)
def invite_member(workspace_id: int, data: InviteCreate, user: CurrentUser, service: WorkspaceService = Depends(get_workspace_service)):
    invite, token = service.invite(workspace_id, user.id, data.email, data.role)
    return {"id": invite.id, "invite_token": token, "role": invite.role}


@router.post("/projects/{project_id}/assets", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
def create_asset(project_id: int, data: AssetCreate, user: CurrentUser, service: ProjectService = Depends(get_project_service)):
    return service.create_asset(project_id, user, data)


@router.post("/assets/{asset_id}/comments", status_code=status.HTTP_201_CREATED)
def create_comment(
    asset_id: int,
    data: CommentCreate,
    response: Response,
    user: CurrentUser,
    service: ProjectService = Depends(get_project_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    data = data.model_copy(update={"client_request_id": idempotency_key or data.client_request_id})
    item, created = service.add_comment(asset_id, user, data)
    response.headers["X-Idempotent-Replay"] = "false" if created else "true"
    return {"id": item.id, "body": item.body, "author_id": item.author_id}


@router.patch("/assets/{asset_id}/status", response_model=AssetRead)
def update_status(asset_id: int, data: StatusUpdate, user: CurrentUser, service: ProjectService = Depends(get_project_service)):
    return service.update_status(asset_id, user, data.status)
