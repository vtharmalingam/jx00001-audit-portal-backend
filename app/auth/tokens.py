"""JWT token creation, decoding, and cookie helpers."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Response
from jose import JWTError, jwt

from app.auth.config import get_auth_config


def create_access_token(data: Dict[str, Any]) -> str:
    cfg = get_auth_config()
    expire = datetime.now(timezone.utc) + timedelta(minutes=cfg.access_token_expire_minutes)
    payload = {**data, "exp": expire, "type": "access"}
    return jwt.encode(payload, cfg.jwt_secret_key, algorithm=cfg.algorithm)


def create_refresh_token(data: Dict[str, Any]) -> str:
    cfg = get_auth_config()
    expire = datetime.now(timezone.utc) + timedelta(days=cfg.refresh_token_expire_days)
    payload = {**data, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, cfg.jwt_secret_key, algorithm=cfg.algorithm)


def create_invite_token(data: Dict[str, Any]) -> str:
    cfg = get_auth_config()
    expire = datetime.now(timezone.utc) + timedelta(hours=cfg.invite_token_expire_hours)
    payload = {**data, "exp": expire, "type": "invite"}
    return jwt.encode(payload, cfg.jwt_secret_key, algorithm=cfg.algorithm)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate a JWT. Returns claims dict or None if invalid/expired."""
    cfg = get_auth_config()
    try:
        return jwt.decode(token, cfg.jwt_secret_key, algorithms=[cfg.algorithm])
    except JWTError:
        return None


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set HttpOnly cookies for access and refresh tokens."""
    cfg = get_auth_config()

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=cfg.cookie_secure,
        samesite=cfg.cookie_samesite,
        path="/api",
        max_age=cfg.access_token_expire_minutes * 60,
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=cfg.cookie_secure,
        samesite=cfg.cookie_samesite,
        path="/api/v1/auth/refresh",
        max_age=cfg.refresh_token_expire_days * 86400,
    )


def clear_auth_cookies(response: Response) -> None:
    """Delete both auth cookies."""
    response.delete_cookie(key="access_token", path="/api")
    response.delete_cookie(key="refresh_token", path="/api/v1/auth/refresh")
