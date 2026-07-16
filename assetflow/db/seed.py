from sqlalchemy import select
from sqlalchemy.orm import Session

from assetflow.core.security import hash_password
from assetflow.db.models import (
    Asset,
    AssetStatus,
    AssetVersion,
    Comment,
    Project,
    RevisionTask,
    Role,
    User,
    Workspace,
    WorkspaceMember,
)


def seed_demo(db: Session) -> None:
    if db.scalar(select(User).limit(1)):
        return

    designer = User(
        email="designer@assetflow.demo",
        name="Studio Designer",
        password_hash=hash_password("AssetFlow123!"),
    )
    collaborator = User(
        email="maya@assetflow.demo",
        name="Maya Chen",
        password_hash=hash_password("AssetFlow123!"),
    )
    workspace = Workspace(name="AssetFlow Studio", slug="assetflow-studio")
    db.add_all([designer, collaborator, workspace])
    db.flush()
    db.add_all(
        [
            WorkspaceMember(
                workspace_id=workspace.id, user_id=designer.id, role=Role.OWNER
            ),
            WorkspaceMember(
                workspace_id=workspace.id, user_id=collaborator.id, role=Role.DESIGNER
            ),
        ]
    )

    specs = [
        (
            "Essentials Drop",
            "Northline",
            "Wear Less Noise",
            "Campaign poster",
            AssetStatus.CHANGES_REQUESTED,
            "/static/demo/essentials-streetwear.png",
        ),
        (
            "Heritage Launch",
            "Naya Atelier",
            "Rooted in Heritage",
            "Fashion campaign",
            AssetStatus.IN_REVIEW,
            "/static/demo/heritage-fashion.png",
        ),
        (
            "Burst Energy",
            "Burst",
            "Full Energy Launch",
            "Product social ad",
            AssetStatus.IN_REVIEW,
            "/static/demo/burst-energy.png",
        ),
        (
            "Apex Motion",
            "Apex",
            "Power in Motion",
            "Sportswear poster",
            AssetStatus.APPROVED,
            "/static/demo/apex-sportswear.png",
        ),
        (
            "Lookbook 01",
            "Lune",
            "Live in Style",
            "Editorial poster",
            AssetStatus.DRAFT,
            "/static/demo/lookbook-poster.png",
        ),
        (
            "Summer Escape",
            "Atlas Travel",
            "Travel the World",
            "Travel campaign",
            AssetStatus.FINAL_DELIVERED,
            "/static/demo/travel-poster.png",
        ),
    ]

    assets: dict[str, Asset] = {}
    for project_name, client, title, kind, status, image in specs:
        project = Project(
            workspace_id=workspace.id,
            name=project_name,
            client_name=client,
            description=f"Campaign workspace for {client}.",
            client_review_enabled=True,
        )
        db.add(project)
        db.flush()
        asset = Asset(
            project_id=project.id,
            title=title,
            asset_type=kind,
            status=status,
            assigned_designer_id=designer.id,
        )
        db.add(asset)
        db.flush()
        db.add(
            AssetVersion(
                asset_id=asset.id,
                number=1,
                file_url=image,
                notes="Initial creative direction",
                uploaded_by_id=designer.id,
            )
        )
        assets[title] = asset

    focus = assets["Wear Less Noise"]
    db.add(
        AssetVersion(
            asset_id=focus.id,
            number=2,
            file_url="/static/demo/essentials-streetwear.png",
            notes="Refined type scale and CTA spacing",
            uploaded_by_id=designer.id,
        )
    )
    opening = Comment(
        asset_id=focus.id,
        author_id=designer.id,
        body="Just uploaded v2. The headline has more breathing room — let me know what you think! 🎨",
    )
    db.add(opening)
    db.flush()
    client_reply = Comment(
        asset_id=focus.id,
        guest_name="Alex Morgan",
        guest_role="client",
        body="This is looking strong! Could we make the CTA slightly warmer and lift it away from the edge? 👍",
        parent_id=opening.id,
    )
    db.add(client_reply)
    db.flush()
    db.add(
        Comment(
            asset_id=focus.id,
            author_id=designer.id,
            body="Absolutely — I’ll tune the CTA colour and spacing in the next pass. On it! ✨",
            parent_id=client_reply.id,
        )
    )
    db.add_all(
        [
            RevisionTask(
                asset_id=focus.id,
                text="Increase headline weight",
                is_done=True,
                created_by_id=designer.id,
            ),
            RevisionTask(
                asset_id=focus.id,
                text="Warm the CTA colour",
                created_by_id=designer.id,
            ),
            RevisionTask(
                asset_id=focus.id,
                text="Add more space below the CTA",
                created_by_id=designer.id,
            ),
            RevisionTask(
                asset_id=focus.id,
                text="Export final social sizes",
                created_by_id=designer.id,
            ),
        ]
    )

    heritage = assets["Rooted in Heritage"]
    db.add_all(
        [
            Comment(
                asset_id=heritage.id,
                author_id=designer.id,
                body="The updated crop puts the craft details front and centre. 🌴",
            ),
            Comment(
                asset_id=heritage.id,
                guest_name="Naya Team",
                guest_role="client",
                body="Love the energy. Please make the collection button a touch narrower.",
            ),
        ]
    )

    burst = assets["Full Energy Launch"]
    db.add(
        Comment(
            asset_id=burst.id,
            guest_name="Burst Brand",
            guest_role="client",
            body="The pink and yellow hit perfectly. Can the Japanese copy move a little higher? ⚡",
        )
    )
    db.commit()
