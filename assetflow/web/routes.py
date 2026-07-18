import mimetypes
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from assetflow.core.errors import AppError, AuthenticationError, RateLimitError
from assetflow.core.security import token_hash
from assetflow.db.models import (
    Asset,
    AssetStatus,
    AssetVersion,
    Comment,
    Invite,
    Project,
    ReviewLink,
    RevisionTask,
    Role,
    User,
    Workspace,
    WorkspaceMember,
)
from assetflow.db.session import get_db
from assetflow.schemas.auth import SignupRequest
from assetflow.services.auth import AuthService
from assetflow.services.comments import CommentService
from assetflow.services.creative_ai import CreativeAIService
from assetflow.services.reviews import ReviewService
from assetflow.services.workspaces import WorkspaceService

router = APIRouter(include_in_schema=False)
templates = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape())
DASHBOARD_PAGE_SIZE = 6


def render(name: str, request: Request, **context):
    return HTMLResponse(templates.get_template(name).render(request=request, **context))


def web_user(request: Request, db: Session):
    raw = request.cookies.get("assetflow_session")
    if not raw:
        return None
    try:
        return AuthService(db, request.app.state.settings).authenticate(raw)
    except AuthenticationError:
        return None


def membership_for(user_id: int, db: Session) -> WorkspaceMember | None:
    return db.scalar(select(WorkspaceMember).where(WorkspaceMember.user_id == user_id).limit(1))


def require_workspace(request: Request, db: Session):
    user = web_user(request, db)
    membership = membership_for(user.id, db) if user else None
    return user, membership


def authorized_asset(asset_id: int, user_id: int, db: Session) -> Asset | None:
    membership = membership_for(user_id, db)
    if not membership:
        return None
    query = select(Asset).join(Project).where(
        Asset.id == asset_id, Project.workspace_id == membership.workspace_id
    )
    if membership.role == Role.DESIGNER:
        query = query.where(Asset.assigned_designer_id == user_id)
    return db.scalar(query)


def project_cards(db: Session, workspace_id: int):
    colors = ["#C9FF72", "#FFB9A9", "#D7CCFF", "#FFD66F"]
    rows = list(db.scalars(select(Project).where(Project.workspace_id == workspace_id).order_by(Project.id)))
    return [
        {"id": p.id, "name": p.name, "client": p.client_name or "Internal", "color": colors[i % 4]}
        for i, p in enumerate(rows)
    ]


def shell_context(db: Session, user: User, membership: WorkspaceMember, active_nav: str):
    return {
        "projects": project_cards(db, membership.workspace_id),
        "active_nav": active_nav,
        "current_user": user,
        "membership": membership,
        "can_manage": membership.role in {Role.OWNER, Role.CREATIVE_LEAD},
        "visible_role": "Designer",
    }


def asset_query(workspace_id: int, user: User, membership: WorkspaceMember):
    query = (
        select(Asset)
        .join(Project)
        .where(Project.workspace_id == workspace_id)
        .options(
            selectinload(Asset.versions),
            selectinload(Asset.comments),
            selectinload(Asset.tasks),
            selectinload(Asset.assigned_designer),
            selectinload(Asset.project),
        )
    )
    if membership.role == Role.DESIGNER:
        query = query.where(Asset.assigned_designer_id == user.id)
    return query


def asset_card(asset: Asset, review_token: str | None = None):
    version = asset.versions[-1] if asset.versions else None
    total_tasks = len(asset.tasks)
    done_tasks = sum(task.is_done for task in asset.tasks)
    status_labels = {
        AssetStatus.DRAFT: "Draft",
        AssetStatus.IN_REVIEW: "Ready for Review",
        AssetStatus.CHANGES_REQUESTED: "Changes Requested",
        AssetStatus.APPROVED: "Approved",
        AssetStatus.FINAL_DELIVERED: "Completed",
    }
    if version and (version.file_url.startswith("managed://") or version.file_url.startswith("/static/uploads/")):
        image = f"/media/versions/{version.id}"
        if review_token:
            image += f"?token={review_token}"
    else:
        image = version.file_url if version else "/static/hero.svg"
    return {
        "id": asset.id,
        "project_id": asset.project_id,
        "project": asset.project.name,
        "client": asset.project.client_name or "Internal team",
        "title": asset.title,
        "type": asset.asset_type,
        "status": status_labels[asset.status],
        "assignee": (asset.assigned_designer.name[:2] if asset.assigned_designer else "—").upper(),
        "due": "Active",
        "version": version.number if version else 0,
        "image": image,
        "progress": f"{done_tasks}/{total_tasks}" if total_tasks else "0/0",
        "comments": len(asset.comments),
        "preview_delete_after": version.preview_delete_after if version else None,
        "preview_deleted": bool(version and version.preview_deleted_at),
    }


def comment_card(comment: Comment, db: Session):
    if comment.author:
        role, key = "Designer", "designer"
        author = comment.author.name
        initials = "".join(part[0] for part in author.split()[:2]).upper()
    else:
        role, key, author, initials = "Client", "client", comment.guest_name or "Guest", "CL"
    return {
        "id": comment.id,
        "author": author,
        "initials": initials,
        "role": role,
        "role_key": key,
        "text": comment.body,
        "parent_id": comment.parent_id,
        "client_request_id": comment.client_request_id,
        "time": comment.created_at.strftime("%d %b · %I:%M %p") if comment.created_at else "Now",
    }


def valid_comment_parent(parent_id: str, asset_id: int, db: Session) -> int | None:
    if not parent_id.isdigit():
        return None
    parent = db.get(Comment, int(parent_id))
    return parent.id if parent and parent.asset_id == asset_id else None


async def save_upload(file: UploadFile, settings) -> str | None:
    suffix = Path(file.filename or "asset.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}:
        return None
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{suffix}"
    destination = settings.upload_dir / filename
    total = 0
    with destination.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > settings.max_upload_bytes:
                output.close()
                destination.unlink(missing_ok=True)
                raise ValueError("File too large")
            output.write(chunk)
    return f"managed://{filename}"


def preview_path(version: AssetVersion, settings) -> Path | None:
    if version.file_url.startswith("managed://"):
        root = settings.upload_dir.resolve()
        filename = version.file_url.removeprefix("managed://")
    elif version.file_url.startswith("/static/uploads/"):
        root = Path("static/uploads").resolve()
        filename = Path(version.file_url).name
    else:
        return None
    target = (root / filename).resolve()
    return target if target.parent == root else None


def remove_preview_files(paths: list[Path]) -> None:
    """Best-effort cleanup after database deletion has committed."""
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # A maintenance sweep can safely remove a temporarily locked orphan.
            pass


@router.get("/media/versions/{version_id}", response_class=FileResponse)
def protected_preview(
    version_id: int,
    request: Request,
    token: str = "",
    db: Session = Depends(get_db),
):
    version = db.get(AssetVersion, version_id)
    if not version:
        return HTMLResponse("Preview not found", 404)
    review_token = token or request.cookies.get("assetflow_review", "")
    if review_token:
        try:
            _, reviewed_asset = ReviewService(db).resolve(review_token)
        except AppError:
            return HTMLResponse("Preview not found", 404)
        if reviewed_asset.id != version.asset_id:
            return HTMLResponse("Preview not found", 404)
    else:
        user = web_user(request, db)
        if not user or not authorized_asset(version.asset_id, user.id, db):
            return HTMLResponse("Preview not found", 404)
    target = preview_path(version, request.app.state.settings)
    if not target or not target.is_file():
        return HTMLResponse("Preview not found", 404)
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(
        target,
        media_type=media_type,
        filename=None,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        },
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if web_user(request, db):
        return RedirectResponse("/", status_code=303)
    return render("auth/login.html", request)


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    if not email.strip() or not password:
        return RedirectResponse("/login?error=missing", status_code=303)
    try:
        _, token = AuthService(db, request.app.state.settings).login(email, password)
    except AuthenticationError:
        return RedirectResponse("/login?error=invalid", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("assetflow_session", token, httponly=True, samesite="lax", secure=request.app.state.settings.secure_cookies, max_age=request.app.state.settings.access_token_ttl_minutes * 60, path="/")
    return response


@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request, invite: str = "", db: Session = Depends(get_db)):
    if web_user(request, db) and not invite:
        return RedirectResponse("/", status_code=303)
    invitation = None
    if invite:
        invitation = db.scalar(select(Invite).where(Invite.token_hash == token_hash(invite), Invite.accepted_at.is_(None)))
        if invitation:
            workspace = db.get(Workspace, invitation.workspace_id)
            invitation = {"email": invitation.email, "role": invitation.role.value.replace("_", " ").title(), "workspace": workspace.name, "token": invite}
    return render("auth/signup.html", request, invitation=invitation)


@router.post("/signup")
def signup_submit(
    request: Request,
    email: str = Form(""),
    name: str = Form(""),
    password: str = Form(""),
    workspace_name: str = Form(""),
    invite_token: str = Form(""),
    db: Session = Depends(get_db),
):
    service = AuthService(db, request.app.state.settings)
    query = {"error": "invalid_details"}
    if invite_token:
        query["invite"] = invite_token
    try:
        data = SignupRequest(
            email=email.strip(),
            name=name.strip(),
            password=password,
            workspace_name=workspace_name.strip(),
        )
    except ValidationError:
        return RedirectResponse(f"/signup?{urlencode(query)}", status_code=303)
    try:
        _, token = service.signup_invited(data, invite_token) if invite_token else service.signup(data)
    except AppError as exc:
        db.rollback()
        query["error"] = "account_exists" if exc.code == "conflict" else "invalid_invite"
        return RedirectResponse(f"/signup?{urlencode(query)}", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("assetflow_session", token, httponly=True, samesite="lax", secure=request.app.state.settings.secure_cookies, max_age=request.app.state.settings.access_token_ttl_minutes * 60, path="/")
    return response


@router.get("/logout")
@router.post("/logout")
def web_logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("assetflow_session", path="/")
    return response


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    page: int = 1,
    queue: str = "all",
    db: Session = Depends(get_db),
):
    user, membership = require_workspace(request, db)
    if not user or not membership:
        return render("landing.html", request)

    scope = [Project.workspace_id == membership.workspace_id]
    if membership.role == Role.DESIGNER:
        scope.append(Asset.assigned_designer_id == user.id)

    status_counts = dict(
        db.execute(
            select(Asset.status, func.count(Asset.id))
            .join(Project)
            .where(*scope)
            .group_by(Asset.status)
        ).all()
    )
    metrics = {
        "needs_action": status_counts.get(AssetStatus.CHANGES_REQUESTED, 0),
        "in_review": status_counts.get(AssetStatus.IN_REVIEW, 0),
        "completed": status_counts.get(AssetStatus.FINAL_DELIVERED, 0),
        "approved": status_counts.get(AssetStatus.APPROVED, 0),
        "projects": db.scalar(
            select(func.count(func.distinct(Asset.project_id))).join(Project).where(*scope)
        )
        or 0,
    }

    queue_statuses = {
        "needs_action": AssetStatus.CHANGES_REQUESTED,
        "completed": AssetStatus.FINAL_DELIVERED,
        "approved": AssetStatus.APPROVED,
    }
    queue = queue if queue in {"all", *queue_statuses} else "all"
    page = max(page, 1)
    queue_filter = [Asset.status == queue_statuses[queue]] if queue in queue_statuses else []
    total_items = db.scalar(
        select(func.count(Asset.id)).join(Project).where(*scope, *queue_filter)
    ) or 0
    total_pages = max((total_items + DASHBOARD_PAGE_SIZE - 1) // DASHBOARD_PAGE_SIZE, 1)
    page = min(page, total_pages)
    rows = list(
        db.scalars(
            asset_query(membership.workspace_id, user, membership)
            .where(*queue_filter)
            .order_by(Asset.updated_at.desc())
            .offset((page - 1) * DASHBOARD_PAGE_SIZE)
            .limit(DASHBOARD_PAGE_SIZE)
        )
    )
    focus = db.scalar(
        asset_query(membership.workspace_id, user, membership)
        .order_by(Asset.updated_at.desc())
        .limit(1)
    )
    focus_insight = CreativeAIService(db).insight(focus) if focus else None
    return render(
        "dashboard.html",
        request,
        assets=[asset_card(a) for a in rows],
        metrics=metrics,
        focus_asset=focus.id if focus else None,
        focus_title=focus.title if focus else None,
        focus_insight=focus_insight,
        queue=queue,
        pagination={
            "current": page,
            "total_pages": total_pages,
            "total_items": total_items,
            "start": ((page - 1) * DASHBOARD_PAGE_SIZE + 1) if total_items else 0,
            "end": min(page * DASHBOARD_PAGE_SIZE, total_items),
        },
        **shell_context(db, user, membership, "overview"),
    )


@router.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request, db: Session = Depends(get_db)):
    user, membership = require_workspace(request, db)
    if not user or not membership:
        return RedirectResponse("/login", status_code=303)
    rows = list(db.scalars(select(Project).where(Project.workspace_id == membership.workspace_id).options(selectinload(Project.assets)).order_by(Project.updated_at.desc())))
    cards = [{"id": p.id, "name": p.name, "client": p.client_name or "Internal team", "description": p.description, "assets": len(p.assets), "in_review": sum(a.status == AssetStatus.IN_REVIEW for a in p.assets), "approved": sum(a.status == AssetStatus.APPROVED for a in p.assets)} for p in rows]
    return render("projects.html", request, project_rows=cards, **shell_context(db, user, membership, "projects"))


@router.get("/projects/new", response_class=HTMLResponse)
def new_project_page(request: Request, db: Session = Depends(get_db)):
    user, membership = require_workspace(request, db)
    if not user or not membership:
        return RedirectResponse("/login", status_code=303)
    if membership.role == Role.DESIGNER:
        return HTMLResponse("Your role cannot create projects", 403)
    return render("project_new.html", request, **shell_context(db, user, membership, "projects"))


@router.post("/projects")
def create_project(request: Request, name: str = Form(...), client_name: str = Form(""), description: str = Form(""), db: Session = Depends(get_db)):
    user, membership = require_workspace(request, db)
    if not user or not membership:
        return RedirectResponse("/login", status_code=303)
    if membership.role == Role.DESIGNER:
        return HTMLResponse("Your role cannot create projects", 403)
    project = Project(workspace_id=membership.workspace_id, name=name.strip(), client_name=client_name.strip() or None, description=description.strip(), client_review_enabled=bool(client_name.strip()))
    db.add(project)
    db.commit()
    db.refresh(project)
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(project_id: int, request: Request, db: Session = Depends(get_db)):
    user, membership = require_workspace(request, db)
    if not user or not membership:
        return RedirectResponse("/login", status_code=303)
    project = db.scalar(select(Project).where(Project.id == project_id, Project.workspace_id == membership.workspace_id))
    if not project:
        return HTMLResponse("Project not found", 404)
    query = asset_query(membership.workspace_id, user, membership).where(Asset.project_id == project_id).order_by(Asset.updated_at.desc())
    rows = list(db.scalars(query))
    return render(
        "project_detail.html",
        request,
        project=project,
        assets=[asset_card(a) for a in rows],
        project_management=True,
        **shell_context(db, user, membership, "projects"),
    )


@router.post("/projects/{project_id}/delete")
def delete_project(project_id: int, request: Request, db: Session = Depends(get_db)):
    user, membership = require_workspace(request, db)
    if not user or not membership:
        return RedirectResponse("/login", status_code=303)
    if membership.role == Role.DESIGNER:
        return HTMLResponse("Your role cannot delete projects", 403)

    project = db.scalar(
        select(Project)
        .where(Project.id == project_id, Project.workspace_id == membership.workspace_id)
        .options(selectinload(Project.assets).selectinload(Asset.versions))
    )
    if not project:
        return HTMLResponse("Project not found", 404)

    asset_ids = [asset.id for asset in project.assets]
    managed_previews = [
        path
        for asset in project.assets
        for version in asset.versions
        if (path := preview_path(version, request.app.state.settings)) is not None
    ]
    if asset_ids:
        db.execute(update(Comment).where(Comment.asset_id.in_(asset_ids)).values(parent_id=None))
        db.execute(delete(ReviewLink).where(ReviewLink.asset_id.in_(asset_ids)))
    db.delete(project)
    db.commit()
    remove_preview_files(managed_previews)
    return RedirectResponse("/projects", status_code=303)


@router.get("/assets", response_class=HTMLResponse)
def assets_page(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db)):
    user, membership = require_workspace(request, db)
    if not user or not membership:
        return RedirectResponse("/login", status_code=303)
    query = asset_query(membership.workspace_id, user, membership)
    if q.strip():
        query = query.where(or_(Asset.title.ilike(f"%{q.strip()}%"), Project.name.ilike(f"%{q.strip()}%")))
    if status:
        try:
            query = query.where(Asset.status == AssetStatus(status))
        except ValueError:
            pass
    rows = list(db.scalars(query.order_by(Asset.updated_at.desc())))
    return render("assets.html", request, assets=[asset_card(a) for a in rows], page_title="All assets", page_kicker="Creative workspace", q=q, **shell_context(db, user, membership, "assets"))


@router.get("/approvals", response_class=HTMLResponse)
def approvals_page(request: Request, db: Session = Depends(get_db)):
    user, membership = require_workspace(request, db)
    if not user or not membership:
        return RedirectResponse("/login", status_code=303)
    rows = list(db.scalars(asset_query(membership.workspace_id, user, membership).where(Asset.status.in_([AssetStatus.IN_REVIEW, AssetStatus.FINAL_DELIVERED, AssetStatus.CHANGES_REQUESTED, AssetStatus.APPROVED])).order_by(Asset.updated_at.desc())))
    return render("assets.html", request, assets=[asset_card(a) for a in rows], page_title="Approvals", page_kicker="Decision queue", q="", **shell_context(db, user, membership, "approvals"))


@router.get("/assets/new", response_class=HTMLResponse)
def new_asset_page(request: Request, project_id: int | None = None, db: Session = Depends(get_db)):
    user, membership = require_workspace(request, db)
    if not user or not membership:
        return RedirectResponse("/login", status_code=303)
    rows = list(db.scalars(select(Project).where(Project.workspace_id == membership.workspace_id).order_by(Project.name)))
    return render("asset_new.html", request, project_rows=rows, selected_project=project_id, max_mb=request.app.state.settings.max_upload_bytes // 1024 // 1024, **shell_context(db, user, membership, "assets"))


@router.post("/assets")
async def create_asset(
    request: Request,
    project_id: str = Form(""),
    title: str = Form(...),
    asset_type: str = Form("Design"),
    notes: str = Form(""),
    new_project_name: str = Form(""),
    new_client_name: str = Form(""),
    file: UploadFile = None,
    db: Session = Depends(get_db),
):
    user, membership = require_workspace(request, db)
    if not user or not membership:
        return RedirectResponse("/login", status_code=303)
    create_inline = project_id == "new"
    if create_inline and membership.role == Role.DESIGNER:
        return HTMLResponse("Your role cannot create projects", 403)
    if create_inline and len(new_project_name.strip()) < 2:
        return HTMLResponse("Enter a project name", 422)
    if not create_inline:
        try:
            selected_project_id = int(project_id)
        except (TypeError, ValueError):
            return HTMLResponse("Choose a project", 422)
        project = db.scalar(
            select(Project).where(
                Project.id == selected_project_id,
                Project.workspace_id == membership.workspace_id,
            )
        )
        if not project:
            return HTMLResponse("Project not found", 404)
    if not file:
        return HTMLResponse("Choose a design preview", 422)
    try:
        file_url = await save_upload(file, request.app.state.settings)
    except ValueError:
        return HTMLResponse("File too large", 413)
    if not file_url:
        return HTMLResponse("Unsupported file type", 415)
    if create_inline:
        project = Project(
            workspace_id=membership.workspace_id,
            name=new_project_name.strip(),
            client_name=new_client_name.strip() or None,
            description="",
            client_review_enabled=bool(new_client_name.strip()),
        )
        db.add(project)
        db.flush()
    asset = Asset(project_id=project.id, title=title.strip(), asset_type=asset_type.strip(), status=AssetStatus.IN_REVIEW, assigned_designer_id=user.id)
    db.add(asset)
    db.flush()
    db.add(AssetVersion(asset_id=asset.id, number=1, file_url=file_url, notes=notes.strip(), uploaded_by_id=user.id))
    db.commit()
    return RedirectResponse(f"/assets/{asset.id}", status_code=303)


@router.get("/assets/{asset_id}", response_class=HTMLResponse)
def asset_detail(asset_id: int, request: Request, db: Session = Depends(get_db)):
    user, membership = require_workspace(request, db)
    if not user or not membership:
        return RedirectResponse("/login", status_code=303)
    if not authorized_asset(asset_id, user.id, db):
        return HTMLResponse("Asset not found", 404)
    asset = db.scalar(select(Asset).where(Asset.id == asset_id).options(selectinload(Asset.versions), selectinload(Asset.comments).selectinload(Comment.author), selectinload(Asset.tasks), selectinload(Asset.assigned_designer), selectinload(Asset.project)))
    comments = [comment_card(comment, db) for comment in asset.comments]
    tasks = [{"id": task.id, "text": task.text, "done": task.is_done} for task in asset.tasks]
    ai_insight = CreativeAIService(db).insight(asset)
    return render("asset.html", request, asset=asset_card(asset), comments=comments, tasks=tasks, ai_insight=ai_insight, comment_request_id=uuid4().hex, max_mb=request.app.state.settings.max_upload_bytes // 1024 // 1024, **shell_context(db, user, membership, "assets"))


@router.post("/assets/{asset_id}/comments", response_class=HTMLResponse)
def add_comment(
    asset_id: int,
    request: Request,
    text: str = Form(...),
    parent_id: str = Form(""),
    client_request_id: str = Form(""),
    db: Session = Depends(get_db),
):
    user = web_user(request, db)
    asset = authorized_asset(asset_id, user.id, db) if user else None
    if not asset:
        return HTMLResponse("Asset not found", 404)
    item, created = CommentService(db).create(
        asset_id=asset_id,
        author_id=user.id,
        body=text.strip(),
        parent_id=valid_comment_parent(parent_id, asset_id, db),
        client_request_id=client_request_id,
    )
    item.author = user
    response = render(
        "partials/comment_with_status.html",
        request,
        comment=comment_card(item, db),
        asset=asset_card(asset),
        status_target="status-wrap",
    )
    response.headers["X-Idempotent-Replay"] = "false" if created else "true"
    return response


@router.post("/assets/{asset_id}/change-request")
def request_asset_changes(
    asset_id: int,
    request: Request,
    text: str = Form(...),
    db: Session = Depends(get_db),
):
    user = web_user(request, db)
    asset = authorized_asset(asset_id, user.id, db) if user else None
    if not asset:
        return HTMLResponse("Asset not found", 404)
    return HTMLResponse("Only clients can request changes", 403)


@router.post("/assets/{asset_id}/status", response_class=HTMLResponse)
def set_status(asset_id: int, request: Request, status: str = Form(...), db: Session = Depends(get_db)):
    user = web_user(request, db)
    asset = authorized_asset(asset_id, user.id, db) if user else None
    if not asset:
        return HTMLResponse("Asset not found", 404)
    try:
        requested = AssetStatus(status.lower().replace(" ", "_"))
    except ValueError:
        return HTMLResponse("Invalid status", 422)
    if requested in {AssetStatus.APPROVED, AssetStatus.CHANGES_REQUESTED}:
        return HTMLResponse("Only clients can make review decisions", 403)
    asset.status = requested
    if requested != AssetStatus.FINAL_DELIVERED:
        asset.approved_at = None
        for version in asset.versions:
            if not version.preview_deleted_at:
                version.preview_delete_after = None
    db.commit()
    return render("partials/status.html", request, asset=asset_card(asset))


@router.post("/assets/{asset_id}/designer-action", response_class=HTMLResponse)
def designer_action(
    asset_id: int,
    request: Request,
    action: str = Form(...),
    db: Session = Depends(get_db),
):
    user = web_user(request, db)
    asset = authorized_asset(asset_id, user.id, db) if user else None
    if not asset:
        return HTMLResponse("Asset not found", 404)
    if action != "done":
        return HTMLResponse("Unknown designer action", 422)
    asset.status = AssetStatus.FINAL_DELIVERED
    asset.approved_at = None
    for version in asset.versions:
        if not version.preview_deleted_at:
            version.preview_delete_after = None
    db.commit()
    return render(
        "partials/designer_actions.html",
        request,
        asset=asset_card(asset),
        update_status=True,
    )


@router.post("/assets/{asset_id}/delete")
def delete_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    user = web_user(request, db)
    asset = authorized_asset(asset_id, user.id, db) if user else None
    if not asset:
        return HTMLResponse("Asset not found", 404)

    project_id = asset.project_id
    managed_previews = [
        path
        for version in asset.versions
        if (path := preview_path(version, request.app.state.settings)) is not None
    ]

    # Review links are intentionally not exposed as an ORM collection, so remove
    # them explicitly. Detaching replies first keeps deletion reliable when
    # SQLite foreign-key checks are enabled.
    db.execute(update(Comment).where(Comment.asset_id == asset_id).values(parent_id=None))
    db.execute(delete(ReviewLink).where(ReviewLink.asset_id == asset_id))
    db.delete(asset)
    db.commit()

    remove_preview_files(managed_previews)

    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/assets/{asset_id}/versions")
async def upload_version(asset_id: int, request: Request, file: UploadFile, notes: str = Form(""), db: Session = Depends(get_db)):
    user = web_user(request, db)
    asset = authorized_asset(asset_id, user.id, db) if user else None
    if not asset:
        return HTMLResponse("Asset not found", 404)
    try:
        file_url = await save_upload(file, request.app.state.settings)
    except ValueError:
        return HTMLResponse("File too large", 413)
    if not file_url:
        return HTMLResponse("Unsupported file type", 415)
    number = (db.scalar(select(func.max(AssetVersion.number)).where(AssetVersion.asset_id == asset_id)) or 0) + 1
    db.add(AssetVersion(asset_id=asset_id, number=number, file_url=file_url, notes=notes.strip(), uploaded_by_id=user.id))
    asset.status = AssetStatus.IN_REVIEW
    asset.approved_at = None
    db.commit()
    return RedirectResponse(f"/assets/{asset_id}", status_code=303)


@router.post("/assets/{asset_id}/tasks", response_class=HTMLResponse)
def add_task(asset_id: int, request: Request, text: str = Form(...), db: Session = Depends(get_db)):
    user = web_user(request, db)
    asset = authorized_asset(asset_id, user.id, db) if user else None
    if not asset:
        return HTMLResponse("Asset not found", 404)
    task = RevisionTask(asset_id=asset_id, text=text.strip(), created_by_id=user.id)
    db.add(task)
    db.commit()
    db.refresh(task)
    return render("partials/task.html", request, task={"id": task.id, "text": task.text, "done": False})


@router.post("/assets/{asset_id}/ai/tasks", response_class=HTMLResponse)
def generate_ai_tasks(asset_id: int, request: Request, db: Session = Depends(get_db)):
    user = web_user(request, db)
    asset = authorized_asset(asset_id, user.id, db) if user else None
    if not asset:
        return HTMLResponse("Asset not found", 404)
    service = CreativeAIService(db, request.app.state.settings)
    try:
        tasks = service.extract_tasks(asset, user)
    except RateLimitError as exc:
        return render("partials/ai_task_notice.html", request, message=exc.message)
    if not tasks:
        return render("partials/ai_task_notice.html", request)
    return render(
        "partials/generated_tasks.html",
        request,
        tasks=[{"id": task.id, "text": task.text, "done": False} for task in tasks],
    )


@router.post("/assets/{asset_id}/ai/summary", response_class=HTMLResponse)
def generate_ai_summary(asset_id: int, request: Request, db: Session = Depends(get_db)):
    user = web_user(request, db)
    asset = authorized_asset(asset_id, user.id, db) if user else None
    if not asset:
        return HTMLResponse("Asset not found", 404)
    asset = db.scalar(
        select(Asset)
        .where(Asset.id == asset_id)
        .options(selectinload(Asset.comments), selectinload(Asset.tasks))
    )
    try:
        result = CreativeAIService(db, request.app.state.settings).summarize(asset, user)
    except RateLimitError as exc:
        result = {"available": False, "message": exc.message}
    return render("partials/ai_summary.html", request, asset_id=asset_id, ai_result=result)


@router.post("/tasks/{task_id}/toggle", response_class=HTMLResponse)
def toggle_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = web_user(request, db)
    task = db.get(RevisionTask, task_id)
    if not user or not task or not authorized_asset(task.asset_id, user.id, db):
        return HTMLResponse("Task not found", 404)
    task.is_done = not task.is_done
    db.commit()
    return render("partials/task.html", request, task={"id": task.id, "text": task.text, "done": task.is_done})


@router.post("/assets/{asset_id}/review-links", response_class=HTMLResponse)
def create_review_link(asset_id: int, request: Request, db: Session = Depends(get_db)):
    user = web_user(request, db)
    asset = authorized_asset(asset_id, user.id, db) if user else None
    if not asset:
        return HTMLResponse("Asset not found", 404)
    _, token = ReviewService(db).create_link(asset)
    url = str(request.base_url).rstrip("/") + f"/review/t/{token}"
    return render("partials/review_link.html", request, review_url=url)


@router.get("/review/t/{token}", response_class=HTMLResponse)
def public_review(token: str, request: Request, db: Session = Depends(get_db)):
    try:
        _, asset = ReviewService(db).resolve(token)
    except AppError:
        return render("review_expired.html", request)
    asset = db.scalar(select(Asset).where(Asset.id == asset.id).options(selectinload(Asset.versions), selectinload(Asset.comments).selectinload(Comment.author), selectinload(Asset.tasks), selectinload(Asset.assigned_designer), selectinload(Asset.project)))
    response = render(
        "review.html",
        request,
        token=token,
        asset=asset_card(asset),
        comments=[comment_card(c, db) for c in asset.comments],
        comment_request_id=uuid4().hex,
        change_request_id=uuid4().hex,
    )
    # Scope the secret to preview requests instead of repeating it in image URLs.
    response.set_cookie(
        "assetflow_review",
        token,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.secure_cookies,
        max_age=60 * 60,
        path="/media/",
    )
    return response


@router.post("/review/t/{token}/comments", response_class=HTMLResponse)
def public_comment(
    token: str,
    request: Request,
    name: str = Form(...),
    text: str = Form(...),
    parent_id: str = Form(""),
    client_request_id: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        _, asset = ReviewService(db).resolve(token)
    except AppError:
        return HTMLResponse("Review link expired", 404)
    def mark_changes_requested() -> None:
        asset.status = AssetStatus.CHANGES_REQUESTED
        asset.approved_at = None
        for version in asset.versions:
            if not version.preview_deleted_at:
                version.preview_delete_after = None

    item, created = CommentService(db).create(
        asset_id=asset.id,
        guest_name=name.strip(),
        guest_role="client",
        body=text.strip(),
        parent_id=valid_comment_parent(parent_id, asset.id, db),
        client_request_id=client_request_id,
        before_commit=mark_changes_requested,
    )
    response = render(
        "partials/comment_with_status.html",
        request,
        comment=comment_card(item, db),
        asset=asset_card(asset),
        status_target="review-status",
        public=True,
    )
    response.headers["X-Idempotent-Replay"] = "false" if created else "true"
    return response


@router.post("/review/t/{token}/change-request")
def public_change_request(
    token: str,
    request: Request,
    name: str = Form(...),
    text: str = Form(...),
    client_request_id: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        _, asset = ReviewService(db).resolve(token)
    except AppError:
        return HTMLResponse("Review link expired", 404)
    def mark_changes_requested() -> None:
        asset.status = AssetStatus.CHANGES_REQUESTED
        asset.approved_at = None
        for version in asset.versions:
            if not version.preview_deleted_at:
                version.preview_delete_after = None

    _, created = CommentService(db).create(
        asset_id=asset.id,
        guest_name=name.strip(),
        guest_role="client",
        body=text.strip(),
        client_request_id=client_request_id,
        before_commit=mark_changes_requested,
    )
    response = RedirectResponse(f"/review/t/{token}", status_code=303)
    response.headers["X-Idempotent-Replay"] = "false" if created else "true"
    return response


@router.post("/review/t/{token}/decision", response_class=HTMLResponse)
def public_decision(token: str, request: Request, status: str = Form(...), db: Session = Depends(get_db)):
    try:
        asset = ReviewService(db).decide(token, AssetStatus(status), request.app.state.settings.approved_preview_retention_days)
    except (AppError, ValueError):
        return HTMLResponse("Decision could not be saved", 422)
    return render("partials/status.html", request, asset=asset_card(asset))


@router.get("/team/invite", response_class=HTMLResponse)
def invite_page(request: Request, db: Session = Depends(get_db)):
    user, membership = require_workspace(request, db)
    if not user or not membership:
        return RedirectResponse("/login", status_code=303)
    if membership.role == Role.DESIGNER:
        return HTMLResponse("Your role cannot invite members", 403)
    return render("invite.html", request, invite_url=None, **shell_context(db, user, membership, "team"))


@router.post("/team/invite", response_class=HTMLResponse)
def invite_submit(request: Request, email: str = Form(...), role: str = Form(...), db: Session = Depends(get_db)):
    user, membership = require_workspace(request, db)
    if not user or not membership:
        return RedirectResponse("/login", status_code=303)
    try:
        _, token = WorkspaceService(db, request.app.state.settings).invite(membership.workspace_id, user.id, email, Role(role))
    except (AppError, ValueError) as exc:
        return HTMLResponse(getattr(exc, "message", "Invite could not be created"), 422)
    invite_url = str(request.base_url).rstrip("/") + f"/signup?invite={token}"
    return render("invite.html", request, invite_url=invite_url, **shell_context(db, user, membership, "team"))
