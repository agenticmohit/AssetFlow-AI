import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from assetflow.db.base import Base


class Role(str, enum.Enum):
    OWNER = "owner"
    CREATIVE_LEAD = "creative_lead"
    DESIGNER = "designer"


class AssetStatus(str, enum.Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    FINAL_DELIVERED = "final_delivered"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    memberships: Mapped[list["WorkspaceMember"]] = relationship(back_populates="user")


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    members: Mapped[list["WorkspaceMember"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMember(TimestampMixin, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[Role] = mapped_column(Enum(Role))
    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    client_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    client_review_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    workspace: Mapped[Workspace] = relationship()
    assets: Mapped[list["Asset"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Asset(TimestampMixin, Base):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    asset_type: Mapped[str] = mapped_column(String(80), default="Design")
    status: Mapped[AssetStatus] = mapped_column(Enum(AssetStatus), default=AssetStatus.DRAFT, index=True)
    assigned_designer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    project: Mapped[Project] = relationship(back_populates="assets")
    assigned_designer: Mapped[User | None] = relationship()
    versions: Mapped[list["AssetVersion"]] = relationship(back_populates="asset", cascade="all, delete-orphan", order_by="AssetVersion.number")
    comments: Mapped[list["Comment"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
    tasks: Mapped[list["RevisionTask"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
    ai_requests: Mapped[list["AIRequestLog"]] = relationship(cascade="all, delete-orphan")


class AssetVersion(TimestampMixin, Base):
    __tablename__ = "asset_versions"
    __table_args__ = (UniqueConstraint("asset_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    number: Mapped[int]
    file_url: Mapped[str] = mapped_column(String(500))
    notes: Mapped[str] = mapped_column(Text, default="")
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    preview_delete_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    preview_deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    asset: Mapped[Asset] = relationship(back_populates="versions")
    uploaded_by: Mapped[User] = relationship()


class Comment(TimestampMixin, Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    guest_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    guest_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"), nullable=True)
    asset: Mapped[Asset] = relationship(back_populates="comments")
    author: Mapped[User | None] = relationship(foreign_keys=[author_id])


class RevisionTask(TimestampMixin, Base):
    __tablename__ = "revision_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(500))
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    asset: Mapped[Asset] = relationship(back_populates="tasks")
    created_by: Mapped[User | None] = relationship()


class AccessToken(TimestampMixin, Base):
    __tablename__ = "access_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Invite(TimestampMixin, Base):
    __tablename__ = "invites"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[Role] = mapped_column(Enum(Role))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReviewLink(TimestampMixin, Base):
    __tablename__ = "review_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AIRequestLog(Base):
    __tablename__ = "ai_request_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
