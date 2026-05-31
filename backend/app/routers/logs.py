from fastapi import APIRouter, Depends, Response
import csv
import io
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


def _serialize_log(log):
    return {
        "id": log.id,
        "timestamp": log.timestamp,
        "category": log.category,
        "action": log.action,
        "description": log.description
    }


@router.get("/")
def get_activity_logs(
    category: str = None,
    action: str = None,
    search: str = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    logs = crud.get_logs(db, category=category, action=action, search=search, limit=min(limit, 1000))
    return [_serialize_log(log) for log in logs]


@router.get("/export")
def export_activity_logs(
    category: str = None,
    action: str = None,
    search: str = None,
    limit: int = 1000,
    db: Session = Depends(get_db),
):
    logs = crud.get_logs(db, category=category, action=action, search=search, limit=min(limit, 5000))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "timestamp", "category", "action", "description"])
    for log in logs:
        writer.writerow([log.id, log.timestamp, log.category, log.action, log.description])
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=activity_logs.csv"},
    )
