"""Auth configuration — loaded from config.yaml with env-var overrides."""

import os
from dataclasses import dataclass
from functools import lru_cache

import importlib.resources
import yaml


@dataclass(frozen=True)
class AuthConfig:
    jwt_secret_key: str
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"
    # Cookie settings
    cookie_secure: bool = False  # True in production (HTTPS only)
    cookie_samesite: str = "lax"
    cookie_domain: str = ""  # empty = current domain
    # Invite settings
    invite_token_expire_hours: int = 72  # 3 days
    frontend_base_url: str = "http://localhost:3000"


@lru_cache(maxsize=1)
def get_auth_config() -> AuthConfig:
    path = importlib.resources.files("app") / "config.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    auth_cfg = raw.get("auth", {})

    return AuthConfig(
        jwt_secret_key=os.getenv("JWT_SECRET_KEY", auth_cfg.get("jwt_secret_key", "CHANGE-ME-dev-only")),
        access_token_expire_minutes=int(os.getenv(
            "ACCESS_TOKEN_EXPIRE_MINUTES",
            auth_cfg.get("access_token_expire_minutes", 30),
        )),
        refresh_token_expire_days=int(os.getenv(
            "REFRESH_TOKEN_EXPIRE_DAYS",
            auth_cfg.get("refresh_token_expire_days", 7),
        )),
        algorithm=auth_cfg.get("algorithm", "HS256"),
        cookie_secure=auth_cfg.get("cookie_secure", False),
        cookie_samesite=auth_cfg.get("cookie_samesite", "lax"),
        cookie_domain=auth_cfg.get("cookie_domain", ""),
        invite_token_expire_hours=int(auth_cfg.get("invite_token_expire_hours", 72)),
        frontend_base_url=os.getenv("FRONTEND_BASE_URL", auth_cfg.get("frontend_base_url", "http://localhost:3000")),
    )
