from fastapi import APIRouter, Depends, status

from assetflow.api.dependencies import get_review_service
from assetflow.schemas.projects import GuestCommentCreate, StatusUpdate
from assetflow.services.reviews import ReviewService

router = APIRouter(prefix="/public/reviews", tags=["public reviews"])


@router.get("/{token}")
def review(token: str, service: ReviewService = Depends(get_review_service)):
    _, asset = service.resolve(token)
    return {"id": asset.id, "title": asset.title, "status": asset.status}


@router.post("/{token}/comments", status_code=status.HTTP_201_CREATED)
def comment(token: str, data: GuestCommentCreate, service: ReviewService = Depends(get_review_service)):
    item = service.comment(token, data.name, data.body)
    return {"id": item.id, "name": item.guest_name, "body": item.body}


@router.patch("/{token}/decision")
def decision(token: str, data: StatusUpdate, service: ReviewService = Depends(get_review_service)):
    asset = service.decide(token, data.status)
    return {"id": asset.id, "status": asset.status}

