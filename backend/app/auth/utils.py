import random
import string
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from app.config import settings


def generate_otp(length: int = None) -> str:
    length = length or settings.OTP_LENGTH
    return "".join(random.choices(string.digits, k=length))


def send_otp(identifier: str, code: str) -> None:
    """
    Placeholder for real SMS/Email delivery.
    Phone -> plug in an SMS gateway (e.g. Twilio, MSG91).
    Email -> plug in an email service (e.g. SendGrid, SMTP).
    For now it just logs — replace this with a real provider call.
    """
    print(f"[OTP] Sending code {code} to {identifier}")


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
