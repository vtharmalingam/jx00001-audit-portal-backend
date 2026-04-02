"""Authentication & authorization module — JWT + HttpOnly cookies."""

from app.auth.router import router as auth_router
from app.auth.role_router import router as role_router
from app.auth.permissions import (
    get_permissions,
    has_permission,
    invalidate_cache,
    require_permission,
)

__all__ = [
    "auth_router",
    "role_router",
    "get_permissions",
    "has_permission",
    "invalidate_cache",
    "require_permission",
]
