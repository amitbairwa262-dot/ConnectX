import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app import models, schemas
from app.config import settings
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/api/status", tags=["Status"])

STATUS_LIFETIME_HOURS = 24

MEDIA_RULES = {
    models.StatusType.image: {
        "allowed": {"image/jpeg", "image/png", "image/webp", "image/gif"},
        "max_mb": 10,
    },
    models.StatusType.video: {
        "allowed": {"video/mp4", "video/quicktime", "video/webm"},
        "max_mb": 50,
    },
}


def _to_out(status_row: models.Status, current_user_id: int, db: Session) -> schemas.StatusOut:
    view_count = (
        db.query(models.StatusView).filter(models.StatusView.status_id == status_row.id).count()
    )
    viewed_by_me = (
        db.query(models.StatusView)
        .filter(
            models.StatusView.status_id == status_row.id,
            models.StatusView.viewer_id == current_user_id,
        )
        .first()
        is not None
    )
    out = schemas.StatusOut.model_validate(status_row)
    out.view_count = view_count
    out.viewed_by_me = viewed_by_me
    return out


def _active_query(db: Session):
    now = datetime.now(timezone.utc)
    return (
        db.query(models.Status)
        .options(joinedload(models.Status.user))
        .filter(models.Status.expires_at > now)
    )


@router.post("/text", response_model=schemas.StatusOut)
def create_text_status(
    payload: schemas.CreateTextStatusRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expires_at = datetime.now(timezone.utc) + timedelta(hours=STATUS_LIFETIME_HOURS)
    status_row = models.Status(
        user_id=current_user.id,
        status_type=models.StatusType.text,
        content=payload.content,
        background_color=payload.background_color,
        expires_at=expires_at,
    )
    db.add(status_row)
    db.commit()
    db.refresh(status_row)
    return _to_out(status_row, current_user.id, db)


@router.post("/media", response_model=schemas.StatusOut)
async def create_media_status(
    status_type: str = Form(..., description="image | video"),
    caption: str = Form(""),
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        s_type = models.StatusType(status_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="status_type image ya video hona chahiye")

    rules = MEDIA_RULES.get(s_type)
    if not rules:
        raise HTTPException(status_code=400, detail="Text status ke liye /api/status/text use karo")

    if file.content_type not in rules["allowed"]:
        raise HTTPException(status_code=400, detail=f"Ye file type allowed nahi: {file.content_type}")

    contents = await file.read()
    max_bytes = rules["max_mb"] * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File {rules['max_mb']}MB se badi nahi honi chahiye")

    ext = os.path.splitext(file.filename or "")[1] or ""
    filename = f"{uuid.uuid4().hex}{ext}"
    folder = os.path.join(settings.UPLOAD_DIR, "status_media")
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    with open(filepath, "wb") as f:
        f.write(contents)

    file_url = f"/{filepath.replace(os.sep, '/')}"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=STATUS_LIFETIME_HOURS)

    status_row = models.Status(
        user_id=current_user.id,
        status_type=s_type,
        content=file_url,
        caption=caption,
        expires_at=expires_at,
    )
    db.add(status_row)
    db.commit()
    db.refresh(status_row)
    return _to_out(status_row, current_user.id, db)


@router.get("", response_model=List[schemas.StatusOut])
def status_feed(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sabke active (non-expired) statuses — apna khud ka chhodkar."""
    rows = (
        _active_query(db)
        .filter(models.Status.user_id != current_user.id)
        .order_by(models.Status.created_at.desc())
        .all()
    )
    return [_to_out(r, current_user.id, db) for r in rows]


@router.get("/my", response_model=List[schemas.StatusOut])
def my_statuses(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        _active_query(db)
        .filter(models.Status.user_id == current_user.id)
        .order_by(models.Status.created_at.desc())
        .all()
    )
    return [_to_out(r, current_user.id, db) for r in rows]


@router.get("/{status_id}", response_model=schemas.StatusOut)
def view_status(
    status_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    status_row = (
        db.query(models.Status)
        .options(joinedload(models.Status.user))
        .filter(models.Status.id == status_id)
        .first()
    )
    if not status_row:
        raise HTTPException(status_code=404, detail="Status nahi mila (shayad expire ho gaya)")

    now = datetime.now(timezone.utc)
    expires_at = status_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        raise HTTPException(status_code=404, detail="Ye status expire ho chuka hai")

    # record the view (skip if the owner is viewing their own status, or already viewed)
    if status_row.user_id != current_user.id:
        already = (
            db.query(models.StatusView)
            .filter(
                models.StatusView.status_id == status_id,
                models.StatusView.viewer_id == current_user.id,
            )
            .first()
        )
        if not already:
            db.add(models.StatusView(status_id=status_id, viewer_id=current_user.id))
            db.commit()

    return _to_out(status_row, current_user.id, db)


@router.get("/{status_id}/viewers", response_model=List[schemas.StatusViewerOut])
def get_viewers(
    status_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    status_row = db.query(models.Status).filter(models.Status.id == status_id).first()
    if not status_row:
        raise HTTPException(status_code=404, detail="Status nahi mila")
    if status_row.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Sirf apne status ke viewers dekh sakte ho")

    views = (
        db.query(models.StatusView)
        .options(joinedload(models.StatusView.viewer))
        .filter(models.StatusView.status_id == status_id)
        .order_by(models.StatusView.viewed_at.desc())
        .all()
    )
    return views


@router.delete("/{status_id}")
def delete_status(
    status_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    status_row = db.query(models.Status).filter(models.Status.id == status_id).first()
    if not status_row:
        raise HTTPException(status_code=404, detail="Status nahi mila")
    if status_row.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Sirf apna status delete kar sakte ho")

    db.delete(status_row)
    db.commit()
    return {"message": "Status delete ho gaya"}
