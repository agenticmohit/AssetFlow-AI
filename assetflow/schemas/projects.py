from pydantic import BaseModel, ConfigDict, Field

from assetflow.db.models import AssetStatus, Role


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=5000)
    client_name: str | None = Field(default=None, max_length=160)
    client_review_enabled: bool = False


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workspace_id: int


class AssetCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    asset_type: str = Field(default="Design", max_length=80)
    assigned_designer_id: int | None = None


class AssetRead(AssetCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    status: AssetStatus


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    parent_id: int | None = None
    client_request_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class StatusUpdate(BaseModel):
    status: AssetStatus


class InviteCreate(BaseModel):
    email: str
    role: Role


class GuestCommentCreate(BaseModel):
    name: str = Field(default="Client", max_length=120)
    body: str = Field(min_length=1, max_length=5000)
    client_request_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
