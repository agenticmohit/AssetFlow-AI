from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from assetflow.core.errors import NotFoundError, PermissionDeniedError
from assetflow.db.models import (
    Asset,
    AssetStatus,
    AssetVersion,
    Comment,
    Project,
    RevisionTask,
    Role,
    User,
)
from assetflow.schemas.projects import AssetCreate, CommentCreate, ProjectCreate
from assetflow.services.workspaces import WorkspaceService


class ProjectService:
    def __init__(self, db: Session, workspace_service: WorkspaceService):
        self.db = db
        self.workspaces = workspace_service

    def create_project(self, workspace_id: int, actor: User, data: ProjectCreate) -> Project:
        self.workspaces.require_member(workspace_id, actor.id, {Role.OWNER, Role.CREATIVE_LEAD})
        project = Project(workspace_id=workspace_id, **data.model_dump())
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def list_projects(self, workspace_id: int, actor: User) -> list[Project]:
        member = self.workspaces.require_member(workspace_id, actor.id)
        query = select(Project).where(Project.workspace_id == workspace_id).order_by(Project.created_at.desc())
        if member.role == Role.DESIGNER:
            query = query.join(Project.assets).where(Asset.assigned_designer_id == actor.id).distinct()
        return list(self.db.scalars(query))

    def create_asset(self, project_id: int, actor: User, data: AssetCreate) -> Asset:
        project = self._project(project_id)
        self.workspaces.require_member(project.workspace_id, actor.id, {Role.OWNER, Role.CREATIVE_LEAD})
        if data.assigned_designer_id:
            self.workspaces.require_member(project.workspace_id, data.assigned_designer_id, {Role.DESIGNER, Role.CREATIVE_LEAD, Role.OWNER})
        asset = Asset(project_id=project_id, **data.model_dump())
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def add_comment(self, asset_id: int, actor: User, data: CommentCreate) -> Comment:
        asset = self._asset(asset_id)
        self.workspaces.require_member(asset.project.workspace_id, actor.id)
        comment = Comment(asset_id=asset_id, author_id=actor.id, body=data.body, parent_id=data.parent_id)
        self.db.add(comment)
        self.db.commit()
        self.db.refresh(comment)
        return comment

    def update_status(
        self,
        asset_id: int,
        actor: User,
        status: AssetStatus,
        retention_days: int = 10,
    ) -> Asset:
        asset = self._asset(asset_id)
        self.workspaces.require_member(asset.project.workspace_id, actor.id)
        if status in {AssetStatus.APPROVED, AssetStatus.CHANGES_REQUESTED}:
            raise PermissionDeniedError("Only clients can make review decisions")
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

    def add_task(self, asset_id: int, actor: User, text: str) -> RevisionTask:
        asset = self._asset(asset_id)
        self.workspaces.require_member(asset.project.workspace_id, actor.id)
        task = RevisionTask(asset_id=asset_id, text=text, created_by_id=actor.id)
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def toggle_task(self, task_id: int, actor: User) -> RevisionTask:
        task = self.db.get(RevisionTask, task_id)
        if not task:
            raise NotFoundError("Task not found")
        self.workspaces.require_member(task.asset.project.workspace_id, actor.id)
        task.is_done = not task.is_done
        self.db.commit()
        return task

    def add_version(self, asset_id: int, actor: User, file_url: str, notes: str) -> AssetVersion:
        asset = self._asset(asset_id)
        self.workspaces.require_member(asset.project.workspace_id, actor.id)
        number = (self.db.scalar(select(func.max(AssetVersion.number)).where(AssetVersion.asset_id == asset_id)) or 0) + 1
        version = AssetVersion(asset_id=asset_id, number=number, file_url=file_url, notes=notes, uploaded_by_id=actor.id)
        asset.status = AssetStatus.IN_REVIEW
        self.db.add(version)
        self.db.commit()
        self.db.refresh(version)
        return version

    def _project(self, project_id: int) -> Project:
        project = self.db.get(Project, project_id)
        if not project:
            raise NotFoundError("Project not found")
        return project

    def _asset(self, asset_id: int) -> Asset:
        asset = self.db.get(Asset, asset_id)
        if not asset:
            raise NotFoundError("Asset not found")
        return asset
