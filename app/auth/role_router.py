"""Role management API — AICT admin CRUD for the platform role catalog."""

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import get_optional_user
from app.auth.permissions import invalidate_cache
from app.auth.role_service import RoleService
from app.rest.deps import s3_client

router = APIRouter(prefix="/roles", tags=["roles"])


def _svc() -> RoleService:
    return RoleService(s3_client)


# ── Schemas ────────────────────────────────────────────────────────────────

class RoleBody(BaseModel):
    id: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(..., min_length=1, max_length=200)
    tier: str = ""
    level: str = ""
    description: str = ""
    permissions: List[str] = Field(default_factory=list)


class RolePatchBody(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[List[str]] = None
    tier: Optional[str] = None
    level: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("", summary="List all roles")
async def list_roles(
    tier: Optional[str] = None,
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    roles = _svc().list_roles(tier=tier)
    return {"roles": roles, "total": len(roles)}


@router.get("/{role_id}", summary="Get a single role")
async def get_role(
    role_id: str,
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    role = _svc().get_role(role_id)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": f"Role '{role_id}' not found"})
    return role


@router.post("", summary="Create a new role", status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleBody,
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    try:
        role = _svc().create_role(body.model_dump())
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "DUPLICATE", "message": str(e)}) from e
    invalidate_cache(role["id"])
    return role


@router.patch("/{role_id}", summary="Update a role")
async def update_role(
    role_id: str,
    body: RolePatchBody,
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "EMPTY_PATCH", "message": "No fields to update"})

    role = _svc().update_role(role_id, patch)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": f"Role '{role_id}' not found"})
    invalidate_cache(role_id)
    return role


@router.delete("/{role_id}", summary="Delete a role", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: str,
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    if not _svc().delete_role(role_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": f"Role '{role_id}' not found"})
    invalidate_cache(role_id)


@router.get("/permissions/catalog", summary="List all available permission strings")
async def permission_catalog():
    """Returns the master list of permission strings the platform supports."""
    return {
        "permissions": [
            {"key": "users.manage", "label": "Manage Users", "description": "Create, update, delete users and assign roles"},
            {"key": "org.manage", "label": "Manage Organisations", "description": "Create, update, archive organisations"},
            {"key": "settings.manage", "label": "Platform Settings", "description": "Configure platform-wide settings"},
            {"key": "library.manage", "label": "Manage Control Library", "description": "Create, edit, delete assessment categories and questions"},
            {"key": "library.read", "label": "View Control Library", "description": "Read-only access to published controls"},
            {"key": "assessment.fill", "label": "Fill Assessments", "description": "Edit and submit assessment answers"},
            {"key": "assessment.review", "label": "Review Assessments", "description": "Review submitted answers and provide feedback"},
            {"key": "reports.view", "label": "View Reports", "description": "View gap analysis and audit reports"},
            {"key": "reports.export", "label": "Export Reports", "description": "Download and export gap analysis reports"},
            {"key": "reports.annotate", "label": "Annotate Reports", "description": "Flag and add notes to gap report items"},
            {"key": "onboard.create", "label": "Onboard Clients", "description": "Generate onboarding links for new clients"},
            {"key": "archived.view", "label": "View Archived", "description": "View archived organisations and assessments"},
            {"key": "dashboard.view", "label": "View Dashboard", "description": "Access overview and desk dashboards"},
            {"key": "desk.assigned", "label": "Assigned Desk", "description": "Desk filtered to personally assigned items"},
            {"key": "pipeline.view", "label": "View Pipeline", "description": "View assessment pipeline board and progress across organisations"},
            {"key": "review.opinion", "label": "Issue Opinions", "description": "Issue per-question opinions (clean/qualified/adverse/disclaimer)"},
            {"key": "review.verdict", "label": "Issue Verdicts", "description": "Mark assessment categories as pass or fail"},
            {"key": "review.attestation", "label": "Issue Attestation", "description": "Issue the final project attestation opinion"},
        ]
    }
