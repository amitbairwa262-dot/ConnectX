import os
import secrets
from pydantic_settings import BaseSettings

SECRET_KEY_FILE = ".secret_key"


def _load_secret_key() -> str:
    """JWT signing key. Priority: SECRET_KEY env var / .env  >  .secret_key file  >  newly generated.
    A random key is generated once and saved to .secret_key (git-ignored), so logins survive
    restarts but no secret is ever committed to the repository."""
    env_key = os.getenv("SECRET_KEY")
    if env_key:
        return env_key
    try:
        if os.path.exists(SECRET_KEY_FILE):
            with open(SECRET_KEY_FILE, encoding="utf-8") as f:
                saved = f.read().strip()
            if saved:
                return saved
        key = secrets.token_hex(32)
        with open(SECRET_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(key)
        return key
    except OSError:
        return secrets.token_hex(32)  # read-only folder: works, but logins reset on restart


class Settings(BaseSettings):
    # Database — SQLite for local dev, switch to Postgres URL later for production
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./connectx.db")

    # JWT
    SECRET_KEY: str = _load_secret_key()
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # OTP
    OTP_EXPIRE_MINUTES: int = 5
    OTP_LENGTH: int = 6

    # Uploads
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
    MAX_PROFILE_PHOTO_MB: int = 5

    # AI (Claude API — get a key from console.anthropic.com)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    AI_MODEL: str = os.getenv("AI_MODEL", "claude-haiku-4-5-20251001")

    class Config:
        env_file = ".env"


settings = Settings()
