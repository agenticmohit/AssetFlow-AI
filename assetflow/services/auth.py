import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from assetflow.core.config import Settings
from assetflow.core.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from assetflow.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    password_needs_rehash,
    token_hash,
    verify_password,
)
from assetflow.db.models import Invite, Role, User, Workspace, WorkspaceMember
from assetflow.schemas.auth import SignupRequest


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "workspace"


class AuthService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings

    def signup(self, data: SignupRequest) -> tuple[User, str]:
        if self.db.scalar(select(User).where(User.email == data.email.lower())):
            raise ConflictError("An account with this email already exists")
        base_slug = slugify(data.workspace_name)
        slug, suffix = base_slug, 1
        while self.db.scalar(select(Workspace).where(Workspace.slug == slug)):
            suffix += 1
            slug = f"{base_slug}-{suffix}"
        user = User(email=data.email.lower(), name=data.name, password_hash=hash_password(data.password))
        workspace = Workspace(name=data.workspace_name, slug=slug)
        self.db.add_all([user, workspace])
        self.db.flush()
        self.db.add(WorkspaceMember(user_id=user.id, workspace_id=workspace.id, role=Role.OWNER))
        raw = self._issue_token(user.id)
        self.db.commit()
        return user, raw

    def signup_invited(self, data: SignupRequest, invite_token: str) -> tuple[User, str]:
        if self.db.scalar(select(User).where(User.email == data.email.lower())):
            raise ConflictError("An account with this email already exists")
        invite = self.db.scalar(select(Invite).where(Invite.token_hash == token_hash(invite_token)))
        if not invite or invite.accepted_at or invite.expires_at <= datetime.utcnow():
            raise NotFoundError("Invite is invalid or expired")
        if invite.email != data.email.lower():
            raise PermissionDeniedError("This invitation belongs to another email")
        user = User(email=data.email.lower(), name=data.name, password_hash=hash_password(data.password))
        self.db.add(user)
        self.db.flush()
        self.db.add(WorkspaceMember(user_id=user.id, workspace_id=invite.workspace_id, role=invite.role))
        invite.accepted_at = datetime.utcnow()
        raw = self._issue_token(user.id)
        self.db.commit()
        return user, raw

    def login(self, email: str, password: str) -> tuple[User, str]:
        user = self.db.scalar(select(User).where(User.email == email.lower()))
        if not user or not user.is_active or not verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid email or password")
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        raw = self._issue_token(user.id)
        self.db.commit()
        return user, raw

    def authenticate(self, raw: str) -> User:
        user_id = decode_access_token(
            raw,
            self.settings.secret_key,
            self.settings.jwt_algorithm,
        )
        if user_id is None:
            raise AuthenticationError("Session has expired")
        user = self.db.get(User, user_id)
        if not user or not user.is_active:
            raise AuthenticationError("Account is unavailable")
        return user

    def _issue_token(self, user_id: int) -> str:
        return create_access_token(
            user_id,
            self.settings.secret_key,
            self.settings.jwt_algorithm,
            self.settings.access_token_ttl_minutes,
        )
