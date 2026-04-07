"""
REST §3 Organizations — base path ``/api/v1/organizations``.

Auth scoping is TODO (contract: scope by auth).
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.etl.s3.services.audit_lifecycle_service import AuditLifecycleService
from app.etl.s3.services.export_service import BlockchainExportService
from app.etl.s3.services.operational_service import OperationalService
from app.rest.deps import s3_client
from app.rest.strict_audit_ids import enforce_strict_audit_scope
from app.rest.v1.organizations_schemas import (
    AiSystemCreateBody,
    AuditCreateBody,
    BlockchainExportBody,
    OnboardingDecisionBody,
    OrgUpsertBody,
    ProjectCreateBody,
    ai_system_create_to_dict,
    org_upsert_to_patch,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _svc() -> OperationalService:
    return OperationalService(s3_client)


def _parse_org_types(raw: Optional[str]) -> Optional[List[str]]:
    if raw is None or not str(raw).strip():
        return None
    parts = [p.strip() for p in str(raw).split(",")]
    out = [p for p in parts if p]
    return out or None


@router.get(
    "",
    summary="List organizations",
    description=(
        "Filters match §3.3; `org_type` aliases `onboarded_by_type` (aict-client → aict). "
        "Use `org_types=firm,firm_client` to match any of those channels in one request "
        "(OR). When `org_types` is non-empty, it overrides `org_type` / `onboarded_by` for "
        "channel filtering."
    ),
)
async def list_organizations(
    onboarded_by: Optional[str] = Query(None),
    onboarded_by_id: Optional[str] = Query(None, description="Filter by parent org (e.g. firm ID)"),
    org_type: Optional[str] = Query(
        None,
        description="Same as onboarded_by_type for external docs (aict-client ↔ aict).",
    ),
    org_types: Optional[str] = Query(
        None,
        description="Comma-separated onboarded_by_type values (OR), e.g. firm,firm_client.",
    ),
    aict_approved: Optional[bool] = Query(None),
    stage: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    archived: Optional[bool] = Query(None),
    q: Optional[str] = Query(None, description="Search org_id, name, email"),
    manager_id: Optional[str] = Query(None, description="Filter by assigned manager user ID"),
    practitioner_id: Optional[str] = Query(None, description="Filter by assigned practitioner user ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    svc = _svc()
    parsed_types = _parse_org_types(org_types)
    rows, total = svc.list_organizations_filtered(
        onboarded_by=onboarded_by,
        onboarded_by_id=onboarded_by_id,
        org_type=org_type,
        org_types=parsed_types,
        aict_approved=aict_approved,
        stage=stage,
        status=status,
        archived=archived,
        q=q,
        manager_id=manager_id,
        practitioner_id=practitioner_id,
        page=page,
        page_size=page_size,
    )
    return {"organizations": rows, "total": total}


@router.post("", summary="Create a new organization (auto-generates ULID)")
async def create_organization(body: OrgUpsertBody):
    svc = _svc()
    patch = org_upsert_to_patch(body)
    org = svc.create_org(
        name=patch.get("name", ""),
        email=patch.get("email", ""),
        **{k: v for k, v in patch.items() if k not in ("name", "email")},
    )
    return {"organization": org}


@router.get("/{org_id}", summary="Get a single organization profile")
async def get_organization(org_id: str):
    svc = _svc()
    raw = svc.get_org_profile_raw(org_id)
    if not raw:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Unknown org_id: {org_id}"},
        )
    from app.etl.s3.services.org_normalize import normalize_org
    return {"organization": normalize_org(raw)}


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


@router.delete(
    "/{org_id}",
    summary="Permanently delete an organisation record from S3",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_organization(org_id: str):
    svc = _svc()
    try:
        from app.etl.s3.utils.s3_paths import org_profile_key
        svc.s3.delete_object(org_profile_key(org_id))
        svc._delete_from_org_index(org_id)
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "DELETE_FAILED", "message": str(e)},
        ) from e


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

    # Sync aict_approved to every auth user belonging to this org so they can log in.
    # onboarding_decision() updates the org profile but not auth_users.json — this closes that gap.
    try:
        from app.auth.service import AuthUserService
        auth_svc = AuthUserService(s3_client)
        approved = body.decision.lower().strip() == "approve"
        for u in auth_svc.list_users(org_id=org_id):
            auth_svc.update_user(u["id"], {"aict_approved": approved})
    except Exception:
        pass  # Non-fatal: user can still be backfilled on next login

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


@router.post(
    "/{org_id}/projects",
    status_code=status.HTTP_201_CREATED,
    summary="Create a project (v2 layout)",
)
async def create_project(org_id: str, body: ProjectCreateBody):
    svc = _svc()
    if org_id not in svc.iter_org_ids():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Unknown org_id: {org_id}"},
        )
    if body.project_id and svc.get_project(org_id, body.project_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "CONFLICT", "message": "project_id already exists"},
        )
    doc = svc.create_project(org_id, body.project_name, project_id=body.project_id or None)
    return {"project": doc}


@router.get("/{org_id}/projects", summary="List project ids for org")
async def list_projects(org_id: str):
    svc = _svc()
    if org_id not in svc.iter_org_ids():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Unknown org_id: {org_id}"},
        )
    ids = svc.list_project_ids(org_id)
    return {"org_id": org_id, "project_ids": ids, "total": len(ids)}


@router.get("/{org_id}/projects/{project_id}", summary="Get project.json")
async def get_project(org_id: str, project_id: str):
    svc = _svc()
    doc = svc.get_project(org_id, project_id)
    if not doc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Unknown project"},
        )
    return {"project": doc}


@router.post(
    "/{org_id}/audits",
    status_code=status.HTTP_201_CREATED,
    summary="Create audit (metadata, summary, timeline, AI-system lookup)",
)
async def create_audit(org_id: str, body: AuditCreateBody):
    svc = _svc()
    if org_id not in svc.iter_org_ids():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Unknown org_id: {org_id}"},
        )
    if not svc.get_project(org_id, body.project_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Unknown project_id: {body.project_id}"},
        )

    systems = svc.list_ai_systems(org_id)
    valid_system = any(
        (s.get("system_id") == body.ai_system_id and str(s.get("project_id", "")) == body.project_id)
        for s in systems
    )
    if not valid_system:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_FOUND",
                "message": f"Unknown ai_system_id '{body.ai_system_id}' under project '{body.project_id}'",
            },
        )

    enforce_strict_audit_scope(
        org_id,
        body.audit_id,
        project_id=body.project_id,
        ai_system_id=body.ai_system_id,
        require_audit_id=False,
    )

    meta = AuditLifecycleService(s3_client).create_audit(
        org_id,
        body.project_id,
        body.ai_system_id,
        auditor_id=body.auditor_id or "unknown",
        audit_id=body.audit_id,
    )
    return {"audit": meta}


@router.get("/{org_id}/audits/{audit_id}/metadata", summary="Audit control plane (metadata.json)")
async def get_audit_metadata(
    org_id: str,
    audit_id: str,
    project_id: str = Query(..., min_length=3, max_length=3),
    ai_system_id: str = Query(..., min_length=4, max_length=4),
):
    enforce_strict_audit_scope(
        org_id,
        audit_id,
        project_id=project_id,
        ai_system_id=ai_system_id,
    )
    meta = AuditLifecycleService(s3_client).get_metadata(
        org_id, audit_id, project_id, ai_system_id
    )
    if not meta:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Unknown audit or path scope"},
        )
    return {"metadata": meta}


@router.get("/{org_id}/audits/{audit_id}/summary", summary="Dashboard counters (audit_summary.json)")
async def get_audit_summary(
    org_id: str,
    audit_id: str,
    project_id: str = Query(..., min_length=3, max_length=3),
    ai_system_id: str = Query(..., min_length=4, max_length=4),
    recompute: bool = Query(False, description="If true, scan S3 and refresh summary"),
):
    enforce_strict_audit_scope(
        org_id,
        audit_id,
        project_id=project_id,
        ai_system_id=ai_system_id,
    )
    alc = AuditLifecycleService(s3_client)
    from app.etl.s3.utils.s3_paths import audit_summary_key

    if recompute:
        summary = alc.recompute_audit_summary(org_id, audit_id, project_id, ai_system_id)
    else:
        summary = s3_client.read_json(
            audit_summary_key(org_id, audit_id, project_id, ai_system_id)
        )
        if not summary:
            summary = alc.recompute_audit_summary(
                org_id, audit_id, project_id, ai_system_id
            )
    return {"audit_summary": summary}


@router.post(
    "/{org_id}/audits/{audit_id}/blockchain-export",
    summary="Write exports/blockchain/{audit_id}.json",
)
async def blockchain_export(org_id: str, audit_id: str, body: BlockchainExportBody):
    enforce_strict_audit_scope(
        org_id,
        audit_id,
        project_id=body.project_id,
        ai_system_id=body.ai_system_id,
    )
    raw = OperationalService(s3_client).get_org_profile_raw(org_id)
    try:
        payload = BlockchainExportService(s3_client).write_blockchain_export(
            audit_id,
            org_id,
            body.project_id,
            body.ai_system_id,
            org_profile=raw,
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "EXPORT_FAILED", "message": str(e)},
        ) from e
    return {"export": payload}


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
