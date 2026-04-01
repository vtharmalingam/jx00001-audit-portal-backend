"""Admin S3 operational endpoints for retrieval/reporting scenarios."""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query, status

from app.etl.s3.services.answer_service import AnswerService
from app.etl.s3.services.audit_lifecycle_service import AuditLifecycleService
from app.etl.s3.services.operational_service import OperationalService
from app.etl.s3.services.report_service import ReportService
from app.etl.s3.utils.s3_paths import (
    ai_prefix,
    audit_root,
    evidence_index_key,
    progress_key,
    round_prefix,
    timeline_key,
)
from app.rest.deps import s3_client

router = APIRouter(prefix="/admin/s3", tags=["admin"])


def _check_admin_token(x_admin_token: Optional[str]) -> None:
    expected = os.getenv("ADMIN_TESTS_TOKEN")
    if not expected:
        return
    if x_admin_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Invalid admin token"},
        )


def _scan_json(prefix: str) -> List[Dict]:
    results: List[Dict] = []
    token = None
    while True:
        params: Dict[str, object] = {"Bucket": s3_client.bucket, "Prefix": prefix}
        if token:
            params["ContinuationToken"] = token
        resp = s3_client.client.list_objects_v2(**params)
        for obj in resp.get("Contents", []):
            key = obj.get("Key")
            if not key or not key.endswith(".json"):
                continue
            data = s3_client.read_json(key)
            if data is not None:
                results.append({"key": key, "data": data})
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    return results


@router.get("/orgs/{org_id}/profile", summary="Read organization profile from S3")
async def get_org_profile(org_id: str, x_admin_token: Optional[str] = Header(default=None)):
    _check_admin_token(x_admin_token)
    row = OperationalService(s3_client).get_org_profile_raw(org_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Unknown org_id"},
        )
    return {"org_id": org_id, "profile": row}


@router.get("/orgs/{org_id}/projects", summary="List project ids for org")
async def list_projects(org_id: str, x_admin_token: Optional[str] = Header(default=None)):
    _check_admin_token(x_admin_token)
    svc = OperationalService(s3_client)
    return {"org_id": org_id, "project_ids": svc.list_project_ids(org_id)}


@router.get("/orgs/{org_id}/ai-systems", summary="List org ai systems registry")
async def list_ai_systems(org_id: str, x_admin_token: Optional[str] = Header(default=None)):
    _check_admin_token(x_admin_token)
    svc = OperationalService(s3_client)
    return {"org_id": org_id, "systems": svc.list_ai_systems(org_id)}


@router.get("/audits/{org_id}/{audit_id}/keys", summary="Get computed S3 root keys for scope")
async def get_scope_keys(
    org_id: str,
    audit_id: str,
    project_id: str = Query("0"),
    ai_system_id: str = Query("0"),
    x_admin_token: Optional[str] = Header(default=None),
):
    _check_admin_token(x_admin_token)
    return {
        "audit_root": audit_root(org_id, audit_id, project_id, ai_system_id),
        "timeline_key": timeline_key(org_id, audit_id, project_id, ai_system_id),
        "progress_key": progress_key(org_id, audit_id, project_id, ai_system_id),
        "evidence_index_key": evidence_index_key(org_id, audit_id, project_id, ai_system_id),
    }


@router.get("/audits/{org_id}/{audit_id}/metadata", summary="Read audit metadata.json")
async def get_metadata(
    org_id: str,
    audit_id: str,
    project_id: str = Query("0"),
    ai_system_id: str = Query("0"),
    x_admin_token: Optional[str] = Header(default=None),
):
    _check_admin_token(x_admin_token)
    row = AuditLifecycleService(s3_client).get_metadata(org_id, audit_id, project_id, ai_system_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "metadata.json not found for scope"},
        )
    return {"metadata": row}


@router.get("/audits/{org_id}/{audit_id}/summary", summary="Read/recompute audit_summary.json")
async def get_summary(
    org_id: str,
    audit_id: str,
    project_id: str = Query("0"),
    ai_system_id: str = Query("0"),
    recompute: bool = Query(False),
    x_admin_token: Optional[str] = Header(default=None),
):
    _check_admin_token(x_admin_token)
    svc = AuditLifecycleService(s3_client)
    if recompute:
        row = svc.recompute_audit_summary(org_id, audit_id, project_id, ai_system_id)
    else:
        from app.etl.s3.utils.s3_paths import audit_summary_key

        row = s3_client.read_json(audit_summary_key(org_id, audit_id, project_id, ai_system_id))
    return {"audit_summary": row}


@router.get("/audits/{org_id}/{audit_id}/timeline", summary="Read timeline.json")
async def get_timeline(
    org_id: str,
    audit_id: str,
    project_id: str = Query("0"),
    ai_system_id: str = Query("0"),
    x_admin_token: Optional[str] = Header(default=None),
):
    _check_admin_token(x_admin_token)
    row = s3_client.read_json(timeline_key(org_id, audit_id, project_id, ai_system_id)) or {"events": []}
    return {"timeline": row}


@router.get("/audits/{org_id}/{audit_id}/progress", summary="Read progress.json if present")
async def get_progress(
    org_id: str,
    audit_id: str,
    project_id: str = Query("0"),
    ai_system_id: str = Query("0"),
    x_admin_token: Optional[str] = Header(default=None),
):
    _check_admin_token(x_admin_token)
    return {"progress": s3_client.read_json(progress_key(org_id, audit_id, project_id, ai_system_id))}


@router.get("/audits/{org_id}/{audit_id}/evidence-index", summary="Read evidence_index.json")
async def get_evidence_index(
    org_id: str,
    audit_id: str,
    project_id: str = Query("0"),
    ai_system_id: str = Query("0"),
    x_admin_token: Optional[str] = Header(default=None),
):
    _check_admin_token(x_admin_token)
    return {"evidence_index": s3_client.read_json(evidence_index_key(org_id, audit_id, project_id, ai_system_id)) or {}}


@router.get("/audits/{org_id}/{audit_id}/answers", summary="List current answers")
async def get_answers(
    org_id: str,
    audit_id: str,
    project_id: str = Query("0"),
    ai_system_id: str = Query("0"),
    x_admin_token: Optional[str] = Header(default=None),
):
    _check_admin_token(x_admin_token)
    rows = AnswerService(s3_client).get_all_answers(org_id, audit_id, project_id, ai_system_id)
    return {"total": len(rows), "answers": rows}


@router.get("/audits/{org_id}/{audit_id}/ai-analysis", summary="List current ai_analysis")
async def get_ai_analysis(
    org_id: str,
    audit_id: str,
    project_id: str = Query("0"),
    ai_system_id: str = Query("0"),
    x_admin_token: Optional[str] = Header(default=None),
):
    _check_admin_token(x_admin_token)
    rows = ReportService(s3_client).get_gap_report(org_id, audit_id, project_id, ai_system_id)
    return {"total": len(rows), "ai_analysis": rows}


@router.get("/audits/{org_id}/{audit_id}/auditor-feedback", summary="List current auditor_feedback objects")
async def get_auditor_feedback(
    org_id: str,
    audit_id: str,
    project_id: str = Query("0"),
    ai_system_id: str = Query("0"),
    x_admin_token: Optional[str] = Header(default=None),
):
    _check_admin_token(x_admin_token)
    from app.etl.s3.utils.s3_paths import current_prefix

    prefix = f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/auditor_feedback/"
    rows = _scan_json(prefix)
    return {"total": len(rows), "items": rows}


@router.get("/audits/{org_id}/{audit_id}/report/full", summary="Full audit retrieval view")
async def get_full_report(
    org_id: str,
    audit_id: str,
    project_id: str = Query("0"),
    ai_system_id: str = Query("0"),
    x_admin_token: Optional[str] = Header(default=None),
):
    _check_admin_token(x_admin_token)
    return ReportService(s3_client).get_full_audit_view(org_id, audit_id, project_id, ai_system_id)


@router.get("/audits/{org_id}/{audit_id}/rounds/{round_n}", summary="Read immutable round snapshot files")
async def get_round_snapshot(
    org_id: str,
    audit_id: str,
    round_n: int,
    project_id: str = Query("0"),
    ai_system_id: str = Query("0"),
    x_admin_token: Optional[str] = Header(default=None),
):
    _check_admin_token(x_admin_token)
    pref = round_prefix(org_id, audit_id, round_n, project_id, ai_system_id)
    return {
        "round_prefix": pref,
        "answers": s3_client.read_json(f"{pref}answers.json"),
        "ai_analysis": s3_client.read_json(f"{pref}ai_analysis.json"),
        "auditor_feedback": s3_client.read_json(f"{pref}auditor_feedback.json"),
        "round_summary": s3_client.read_json(f"{pref}round_summary.json"),
    }
