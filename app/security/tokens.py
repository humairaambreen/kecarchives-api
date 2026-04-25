from datetime import datetime, timedelta, timezone
from typing import Any

from jose import jwt

from app.core.config import settings


def _create_token(subject: str, expires_delta: timedelta, kind: str) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": kind,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str) -> str:
    return _create_token(subject, timedelta(minutes=settings.access_token_expire_minutes), "access")


def create_refresh_token(subject: str) -> str:
    return _create_token(subject, timedelta(days=settings.refresh_token_expire_days), "refresh")


def decode_refresh_token(token: str) -> str | None:
    """Validate a refresh token and return the subject (user_id str), or None if invalid/expired."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        sub: str | None = payload.get("sub")
        if payload.get("type") != "refresh" or not sub:
            return None
        return sub
    except Exception:
        return None
