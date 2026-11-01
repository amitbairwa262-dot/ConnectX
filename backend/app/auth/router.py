from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.config import settings
from app.auth.utils import generate_otp, send_otp, create_access_token
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/send-otp")
def send_otp_endpoint(payload: schemas.SendOTPRequest, db: Session = Depends(get_db)):
    try:
        identifier = payload.identifier()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    code = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)

    # invalidate any older unused OTPs for this identifier
    db.query(models.OTP).filter(
        models.OTP.identifier == identifier, models.OTP.is_used == False  # noqa: E712
    ).update({"is_used": True})

    otp_row = models.OTP(identifier=identifier, code=code, expires_at=expires_at)
    db.add(otp_row)
    db.commit()

    send_otp(identifier, code)

    return {"message": f"OTP bhej diya gaya {identifier} par", "expires_in_minutes": settings.OTP_EXPIRE_MINUTES}


@router.post("/verify-otp", response_model=schemas.TokenResponse)
def verify_otp_endpoint(payload: schemas.VerifyOTPRequest, db: Session = Depends(get_db)):
    try:
        identifier = payload.identifier()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    otp_row = (
        db.query(models.OTP)
        .filter(models.OTP.identifier == identifier, models.OTP.is_used == False)  # noqa: E712
        .order_by(models.OTP.created_at.desc())
        .first()
    )

    if not otp_row:
        raise HTTPException(status_code=400, detail="OTP nahi mila, pehle send-otp call karo")

    now = datetime.now(timezone.utc)
    expires_at = otp_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < now:
        raise HTTPException(status_code=400, detail="OTP expire ho gaya, naya OTP mangwao")

    if otp_row.code != payload.code:
        raise HTTPException(status_code=400, detail="OTP galat hai")

    otp_row.is_used = True
    db.commit()

    # find existing user by phone or email
    query = db.query(models.User)
    user = query.filter(
        (models.User.phone == identifier) | (models.User.email == identifier)
    ).first()

    is_new_user = False
    if not user:
        is_new_user = True
        if payload.phone:
            user = models.User(phone=identifier)
        else:
            user = models.User(email=identifier)
        db.add(user)
        db.commit()
        db.refresh(user)

    user.is_online = True
    db.commit()

    token = create_access_token({"sub": str(user.id)})

    return schemas.TokenResponse(
        access_token=token,
        user=schemas.UserOut.model_validate(user),
        is_new_user=is_new_user,
    )


@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user
