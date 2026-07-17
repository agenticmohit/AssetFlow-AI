from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from assetflow.core.config import Settings
from assetflow.core.errors import NotFoundError, PermissionDeniedError
from assetflow.core.security import expires_at, new_token, token_hash
from assetflow.db.models import Invite, Role, User, WorkspaceMember


class WorkspaceService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings

    def require_member(self, workspace_id: int, user_id: int, roles: set[Role] | None = None) -> WorkspaceMember:
        member = self.db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id))
        if not member:
            raise PermissionDeniedError("You do not belong to this workspace")
        if roles and member.role not in roles:
            raise PermissionDeniedError("Your role cannot perform this action")
        return member

    def invite(self, workspace_id: int, actor_id: int, email: str, role: Role) -> tuple[Invite, str]:
        self.require_member(workspace_id, actor_id, {Role.OWNER, Role.CREATIVE_LEAD})
        if role != Role.DESIGNER:
            raise PermissionDeniedError("Make It Pop supports designer invitations only")
        raw, hashed = new_token()
        invite = Invite(workspace_id=workspace_id, email=email.lower(), role=role, token_hash=hashed, expires_at=expires_at(72))
        self.db.add(invite)
        self.db.commit()
        return invite, raw

    def accept_invite(self, raw: str, user: User) -> WorkspaceMember:
        invite = self.db.scalar(select(Invite).where(Invite.token_hash == token_hash(raw)))
        if not invite or invite.accepted_at or invite.expires_at <= datetime.utcnow():
            raise NotFoundError("Invite is invalid or expired")
        if invite.email != user.email:
            raise PermissionDeniedError("This invite belongs to another email address")
        member = WorkspaceMember(workspace_id=invite.workspace_id, user_id=user.id, role=invite.role)
        invite.accepted_at = datetime.utcnow()
        self.db.add(member)
        self.db.commit()
        return member
