"""
Fully dynamic permission system — permissions are loaded from S3 roles.json.

Only `aict_admin` has a hardcoded fallback (all permissions) so the platform
is always bootstrappable.  Every other role's permissions come from the role
catalog managed via the /roles CRUD API.

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

from typing import Dict, FrozenSet, List, Optional

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
PIPELINE_VIEW = "pipeline.view"
REVIEW_OPINION = "review.opinion"
REVIEW_VERDICT = "review.verdict"
REVIEW_ATTESTATION = "review.attestation"
GAP_ANALYSIS_VIEW = "gap_analysis.view"

# ── All permissions (aict_admin bootstrap fallback) ───────────────────────

ALL_PERMISSIONS = frozenset({
    USERS_MANAGE, ORG_MANAGE, SETTINGS_MANAGE, LIBRARY_MANAGE, LIBRARY_READ,
    ASSESSMENT_FILL, ASSESSMENT_REVIEW, REPORTS_VIEW, REPORTS_EXPORT,
    REPORTS_ANNOTATE, ONBOARD_CREATE, ARCHIVED_VIEW, DASHBOARD_VIEW,
    DESK_ASSIGNED, PIPELINE_VIEW, REVIEW_OPINION, REVIEW_VERDICT, REVIEW_ATTESTATION,
    GAP_ANALYSIS_VIEW,
})


# ── Core API ───────────────────────────────────────────────────────────────

def _parse_role(role: str) -> tuple:
    """
    Split role string into (tier, level).
    'firm_manager'       → ('firm', 'manager')
    'individual_admin'   → ('individual', 'admin')
    """
    parts = role.rsplit("_", 1)
    if len(parts) != 2:
        return (role, "")
    return parts[0], parts[1]


def _load_role_permissions(role_id: str) -> Optional[FrozenSet[str]]:
    """Load permissions for a role from S3 via RoleService. Returns None if not found."""
    from app.auth.role_service import RoleService
    from app.rest.deps import s3_client

    svc = RoleService(s3_client)
    role = svc.get_role(role_id)
    if role and role.get("permissions"):
        return frozenset(role["permissions"])
    return None


# Simple dict cache — cleared when roles are updated.
_CACHE: Dict[str, FrozenSet[str]] = {}


def get_permissions(role: str) -> FrozenSet[str]:
    """
    Return the full set of permissions for a given role string.

    Resolution order:
    1. aict_admin → hardcoded ALL_PERMISSIONS (bootstrap/god role)
    2. Any other role → load from S3 roles.json via RoleService
    3. If role not found in S3 → empty set (no permissions)
    """
    if not role:
        return frozenset()

    cached = _CACHE.get(role)
    if cached is not None:
        return cached

    # aict_admin is the bootstrap role — always has all permissions
    if role == "aict_admin":
        _CACHE[role] = ALL_PERMISSIONS
        return ALL_PERMISSIONS

    # Dynamic: load from S3 role catalog
    perms = _load_role_permissions(role)
    if perms is None:
        perms = frozenset()

    _CACHE[role] = perms
    return perms


def invalidate_cache(role_id: Optional[str] = None) -> None:
    """
    Clear the permission cache. Call after role CRUD operations.
    If role_id is given, only that role is evicted; otherwise the entire cache is cleared.
    """
    if role_id:
        _CACHE.pop(role_id, None)
    else:
        _CACHE.clear()


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
