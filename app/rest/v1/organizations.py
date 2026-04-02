"""
REST §3 Organizations — base path ``/api/v1/organizations``.

Auth scoping is TODO (contract: scope by auth).
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.etl.s3.services.audit_lifecycle_service import AuditLifecycleService
from app.etl.s3.services.export_service import BlockchainExportService
from app.etl.s3.services.operational_service import OperationalService
from app.etl.s3.services.round_service import RoundService
from app.rest.deps import s3_client
from app.rest.v1.organizations_schemas import (
    AiSystemCreateBody,
    AuditCreateBody,
    BlockchainExportBody,
    OnboardingDecisionBody,
    OrgUpsertBody,
    ProjectCreateBody,
    RoundSnapshotBody,
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
    onboarded_by_id: Optional[str] = Query(None, description="Filter by parent org (e.g. firm ID)"),
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
        onboarded_by_id=onboarded_by_id,
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


@router.delete(
    "/{org_id}",
    summary="Permanently delete an organisation record from S3",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_organization(org_id: str):
    svc = _svc()
    try:
        svc.s3.delete_object(svc.org_profile_key(org_id))
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
    if svc.get_project(org_id, body.project_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "CONFLICT", "message": "project_id already exists"},
        )
    doc = svc.create_project(org_id, body.project_id, body.project_name)
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
    project_id: str = Query("0"),
    ai_system_id: str = Query("0"),
):
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
    project_id: str = Query("0"),
    ai_system_id: str = Query("0"),
    recompute: bool = Query(False, description="If true, scan S3 and refresh summary"),
):
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


@router.post("/{org_id}/audits/{audit_id}/rounds", summary="Immutable round snapshot")
async def snapshot_round(org_id: str, audit_id: str, body: RoundSnapshotBody):
    try:
        result = RoundService(s3_client).create_round_snapshot(
            org_id,
            audit_id,
            body.round_n,
            project_id=body.project_id,
            ai_system_id=body.ai_system_id,
            trigger=body.trigger,
            triggered_by=body.triggered_by,
            notes=body.notes,
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "ROUND_SNAPSHOT_FAILED", "message": str(e)},
        ) from e
    return result


@router.post(
    "/{org_id}/audits/{audit_id}/blockchain-export",
    summary="Write exports/blockchain/{audit_id}.json",
)
async def blockchain_export(org_id: str, audit_id: str, body: BlockchainExportBody):
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
