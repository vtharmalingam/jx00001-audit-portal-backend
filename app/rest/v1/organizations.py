"""
REST §3 Organizations — base path ``/api/v1/organizations``.

Auth scoping is TODO (contract: scope by auth).
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.etl.s3.services.operational_service import OperationalService
from app.rest.deps import s3_client
from app.rest.v1.organizations_schemas import (
    AiSystemCreateBody,
    OnboardingDecisionBody,
    OrgUpsertBody,
    ai_system_create_to_dict,
    org_upsert_to_patch,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _svc() -> OperationalService:
    return OperationalService(s3_client)


@router.get(
    "",
    summary="List organizations",
    description="Filters match §3.3; `org_type` aliases `onboarded_by_type` (aict-client → aict).",
)
async def list_organizations(
    onboarded_by: Optional[str] = Query(None),
    org_type: Optional[str] = Query(
        None,
        description="Same as onboarded_by_type for external docs (aict-client ↔ aict).",
    ),
    aict_approved: Optional[bool] = Query(None),
    stage: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    archived: Optional[bool] = Query(None),
    q: Optional[str] = Query(None, description="Search org_id, name, email"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    svc = _svc()
    rows, total = svc.list_organizations_filtered(
        onboarded_by=onboarded_by,
        org_type=org_type,
        aict_approved=aict_approved,
        stage=stage,
        status=status,
        archived=archived,
        q=q,
        page=page,
        page_size=page_size,
    )
    return {"organizations": rows, "total": total}


@router.put("/{org_id}", summary="Upsert / replace org profile fields")
@router.patch("/{org_id}", summary="Merge org profile fields")
async def upsert_organization(org_id: str, body: OrgUpsertBody):
    svc = _svc()
    patch = org_upsert_to_patch(body)
    if not patch:
        raw = svc.get_org_profile_raw(org_id)
        if not raw:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": f"Unknown org_id: {org_id}"},
            )
        return {"organization": svc.merge_org_profile(org_id, {})}

    merged = svc.merge_org_profile(org_id, patch)
    return {"organization": merged}


@router.post(
    "/{org_id}/onboarding-decision",
    summary="Approve or reject onboarding",
)
async def onboarding_decision(org_id: str, body: OnboardingDecisionBody):
    svc = _svc()
    try:
        org = svc.onboarding_decision(
            org_id,
            body.decision,
            email=body.email,
            reason=body.reason,
        )
    except ValueError as e:
        if "Unknown" in str(e):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": str(e)},
            ) from e
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "BAD_REQUEST", "message": str(e)},
        ) from e
    return {"organization": org}


@router.post(
    "/{org_id}/ai-systems",
    status_code=status.HTTP_201_CREATED,
    summary="Create AI system under org",
)
async def create_ai_system(org_id: str, body: AiSystemCreateBody):
    svc = _svc()
    if org_id not in svc.iter_org_ids():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Unknown org_id: {org_id}"},
        )
    payload = ai_system_create_to_dict(body)
    system = svc.add_ai_system(org_id, payload)
    return {"system": system}


@router.get("/{org_id}/ai-systems", summary="List AI systems for org")
async def list_ai_systems(
    org_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    stage: Optional[str] = Query(None),
):
    svc = _svc()
    if org_id not in svc.iter_org_ids():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Unknown org_id: {org_id}"},
        )
    systems = svc.filter_ai_systems(org_id, status=status_filter, stage=stage)
    return {"org_id": org_id, "systems": systems, "total": len(systems)}
