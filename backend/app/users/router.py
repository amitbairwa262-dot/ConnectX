import os
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.config import settings
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/api/users", tags=["Users & Profile"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


@router.get("/check-username", response_model=schemas.UsernameAvailableResponse)
def check_username(username: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    clean = username.strip().lower()
    exists = db.query(models.User).filter(models.User.username == clean).first()
    return schemas.UsernameAvailableResponse(username=clean, available=exists is None)


@router.put("/username", response_model=schemas.UserOut)
def set_username(
    payload: schemas.SetUsernameRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = (
        db.query(models.User)
        .filter(models.User.username == payload.username, models.User.id != current_user.id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Ye username pehle se liya gaya hai")

    current_user.username = payload.username
    db.commit()
    db.refresh(current_user)
    return current_user


@router.put("/profile", response_model=schemas.UserOut)
def update_profile(
    payload: schemas.UpdateProfileRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.name is not None:
        current_user.name = payload.name.strip()
    if payload.about is not None:
        current_user.about = payload.about.strip()

    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/profile-photo", response_model=schemas.UserOut)
def upload_profile_photo(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Sirf JPEG, PNG ya WEBP image allowed hai")

    contents = file.file.read()
    max_bytes = settings.MAX_PROFILE_PHOTO_MB * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=400, detail=f"Photo {settings.MAX_PROFILE_PHOTO_MB}MB se badi nahi honi chahiye"
        )

    ext = os.path.splitext(file.filename or "")[1] or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    folder = os.path.join(settings.UPLOAD_DIR, "profile_photos")
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    # remove old photo if it exists, so uploads folder doesn't fill up with orphans
    if current_user.profile_image:
        old_path = current_user.profile_image.lstrip("/")
        if os.path.exists(old_path) and old_path.startswith(settings.UPLOAD_DIR):
            os.remove(old_path)

    current_user.profile_image = f"/{filepath.replace(os.sep, '/')}"
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/search", response_model=List[schemas.UserOut])
def search_users(
    q: str = Query(..., min_length=1),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    like = f"%{q.strip().lower()}%"
    results = (
        db.query(models.User)
        .filter(
            models.User.id != current_user.id,
            (models.User.username.ilike(like))
            | (models.User.name.ilike(like))
            | (models.User.phone.ilike(like)),
        )
        .limit(20)
        .all()
    )
    return results


@router.get("/{user_id}", response_model=schemas.UserOut)
def get_user_by_id(
    user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User nahi mila")
    return user
