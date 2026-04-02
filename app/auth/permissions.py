"""
Permission-based access control — derived from role strings at runtime.

No config file, no database, no hardcoded role lists.
Permissions are derived from the role's LEVEL (admin/manager/practitioner)
with optional TIER overrides (aict/firm/individual).

Usage:
    from app.auth.permissions import has_permission, get_permissions, require_permission

    # Check in code
    if has_permission("firm_manager", "assessment.review"):
        ...

    # FastAPI route guard
    @router.get("/users", dependencies=[Depends(require_permission("users.manage"))])
    async def list_users(): ...

    # Inject user + check
    async def endpoint(user: dict = Depends(require_permission("reports.view"))):
        ...
"""

from typing import Dict, FrozenSet, Optional, Set

from fastapi import Cookie, HTTPException, status

from app.auth.dependencies import get_current_user


# ── Permission strings ─────────────────────────────────────────────────────
# Defined as module-level constants for IDE autocomplete and typo prevention.

USERS_MANAGE = "users.manage"
ORG_MANAGE = "org.manage"
SETTINGS_MANAGE = "settings.manage"
LIBRARY_MANAGE = "library.manage"
LIBRARY_READ = "library.read"
ASSESSMENT_FILL = "assessment.fill"
ASSESSMENT_REVIEW = "assessment.review"
REPORTS_VIEW = "reports.view"
REPORTS_EXPORT = "reports.export"
REPORTS_ANNOTATE = "reports.annotate"
ONBOARD_CREATE = "onboard.create"
ARCHIVED_VIEW = "archived.view"
DASHBOARD_VIEW = "dashboard.view"
DESK_ASSIGNED = "desk.assigned"


# ── Level permissions (apply to ALL tiers) ─────────────────────────────────

_LEVEL_PERMISSIONS: Dict[str, FrozenSet[str]] = {
    "admin": frozenset({
        USERS_MANAGE,
        ORG_MANAGE,
        ONBOARD_CREATE,
        REPORTS_VIEW,
        REPORTS_EXPORT,
        ARCHIVED_VIEW,
        DASHBOARD_VIEW,
        LIBRARY_READ,
    }),
    "manager": frozenset({
        ASSESSMENT_REVIEW,
        REPORTS_VIEW,
        REPORTS_EXPORT,
        REPORTS_ANNOTATE,
        ONBOARD_CREATE,
        ARCHIVED_VIEW,
        DASHBOARD_VIEW,
        LIBRARY_READ,
    }),
    "practitioner": frozenset({
        ASSESSMENT_FILL,
        DASHBOARD_VIEW,
        LIBRARY_READ,
        DESK_ASSIGNED,
    }),
}


# ── Tier-specific overrides (additive — merged on top of level perms) ──────

_TIER_OVERRIDES: Dict[str, Dict[str, FrozenSet[str]]] = {
    "aict": {
        "admin": frozenset({
            SETTINGS_MANAGE,
            LIBRARY_MANAGE,
            ASSESSMENT_FILL,
        }),
    },
}


# ── Core API ───────────────────────────────────────────────────────────────

def _parse_role(role: str) -> tuple:
    """
    Split role string into (tier, level).
    'firm_manager'       → ('firm', 'manager')
    'individual_admin'   → ('individual', 'admin')
    'aict_practitioner'  → ('aict', 'practitioner')
    """
    parts = role.rsplit("_", 1)
    if len(parts) != 2:
        return (role, "")
    return parts[0], parts[1]


def get_permissions(role: str) -> FrozenSet[str]:
    """
    Return the full set of permissions for a given role string.
    Merges level-based defaults with tier-specific overrides.
    Result is cached per unique role string.
    """
    cached = _CACHE.get(role)
    if cached is not None:
        return cached

    tier, level = _parse_role(role)

    perms: Set[str] = set(_LEVEL_PERMISSIONS.get(level, frozenset()))

    tier_overrides = _TIER_OVERRIDES.get(tier, {}).get(level, frozenset())
    perms |= tier_overrides

    result = frozenset(perms)
    _CACHE[role] = result
    return result


# Simple dict cache — roles are a small finite set, no eviction needed.
_CACHE: Dict[str, FrozenSet[str]] = {}


def has_permission(role: str, permission: str) -> bool:
    """Check if a role has a specific permission."""
    return permission in get_permissions(role)


def list_permissions(role: str) -> list:
    """Return sorted list of permissions for a role (useful for /auth/me responses)."""
    return sorted(get_permissions(role))


# ── FastAPI dependency ─────────────────────────────────────────────────────

def require_permission(*permissions: str):
    """
    FastAPI dependency that validates the current user has ALL specified permissions.

    Usage:
        # As route dependency (no user injection):
        @router.get("/admin", dependencies=[Depends(require_permission("settings.manage"))])

        # As parameter dependency (injects user):
        @router.get("/report")
        async def report(user: dict = Depends(require_permission("reports.view"))):
            org_id = user["org_id"]
    """
    required = frozenset(permissions)

    async def _guard(access_token: Optional[str] = Cookie(None)) -> dict:
        user = await get_current_user(access_token)
        user_perms = get_permissions(user["role"])
        missing = required - user_perms

        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INSUFFICIENT_PERMISSIONS",
                    "message": f"Missing permissions: {', '.join(sorted(missing))}",
                    "required": sorted(required),
                    "role": user["role"],
                },
            )

        return user

    return _guard
