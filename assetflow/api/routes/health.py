from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from assetflow.db.session import get_db

router = APIRouter(tags=["operations"])


@router.get("/health/live")
def liveness():
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ready", "database": "connected"}

