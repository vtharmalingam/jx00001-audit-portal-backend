"""FastAPI dependencies for route protection — read JWT from HttpOnly cookie."""

import logging
from typing import Dict, Optional, Set

from fastapi import Cookie, HTTPException, status

from app.auth.tokens import decode_token

logger = logging.getLogger(__name__)


async def get_current_user(access_token: Optional[str] = Cookie(None)) -> Dict:
    """
    Extract and validate the current user from the access_token HttpOnly cookie.
    Use as: current_user: Dict = Depends(get_current_user)
    """
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "NOT_AUTHENTICATED", "message": "Authentication required"},
        )

    claims = decode_token(access_token)
    if not claims or claims.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Invalid or expired token"},
        )

    return {
        "id": claims.get("sub"),
        "email": claims.get("email"),
        "role": claims.get("role"),
        "tier": claims.get("tier"),
        "org_id": claims.get("org_id"),
    }


async def get_optional_user(access_token: Optional[str] = Cookie(None)) -> Optional[Dict]:
    """
    Like get_current_user but returns None instead of 401 when no cookie is present.
    Use for endpoints that work for both authenticated and unauthenticated users.
    """
    if not access_token:
        return None

    claims = decode_token(access_token)
    if not claims or claims.get("type") != "access":
        return None

    return {
        "id": claims.get("sub"),
        "email": claims.get("email"),
        "role": claims.get("role"),
        "tier": claims.get("tier"),
        "org_id": claims.get("org_id"),
    }


def require_roles(*allowed_roles: str):
    """
    Returns a dependency that checks the user's role against an allow-list.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_roles("aict_admin"))])
        async def admin_endpoint(): ...

    Or with injection:
        async def endpoint(user: Dict = Depends(require_roles("aict_admin", "aict_manager"))):
            ...
    """
    allowed: Set[str] = set(allowed_roles)

    async def _guard(access_token: Optional[str] = Cookie(None)) -> Dict:
        user = await get_current_user(access_token)
        if user["role"] not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FORBIDDEN",
                    "message": f"Role '{user['role']}' does not have access to this resource",
                },
            )
        return user

    return _guard
