from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import SessionLocal
from .. import crud

router = APIRouter(prefix="/logs", tags=["Logs"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/")
def get_activity_logs(category: str = None, limit: int = 200, db: Session = Depends(get_db)):
    logs = crud.get_logs(db, category=category, limit=limit)
    return [
        {
            "id": log.id,
            "timestamp": log.timestamp,
            "category": log.category,
            "action": log.action,
            "description": log.description
        }
        for log in logs
    ]