"""Pipeline REST API: board view, assessment submission, gap analysis progress."""

import asyncio
import logging
from typing import Optional

from app.etl.s3.utils.helpers import utc_now

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.permissions import require_permission
from app.etl.s3.services.answer_service import AnswerService
from app.pipeline.models import (
    GapAnalysisStatus,
    PipelineStage,
    STAGE_LABELS,
    STAGE_ORDER,
    SubmitAssessmentBody,
)
from app.pipeline.service import PipelineService
from app.rest.deps import s3_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _svc() -> PipelineService:
    return PipelineService(s3_client)


# ── Board ────────────────────────────────────────────────────────────────────


def _resolve_org_id(user: dict) -> str | None:
    """Resolve user's org_id from multiple sources.

    Order:
    1. user.org_id (from JWT/token if present)
    2. Auth user record's org_id field
    3. Domain lookup (S3 lookups/domains/)
    4. Scan orgs matching email domain
    """
    org_id = user.get("org_id")
    if org_id:
        return org_id

    email = user.get("email", "")
    user_id = user.get("id", "")

    # Try auth user record (may have org_id stored)
    if user_id:
        try:
            from app.auth.service import AuthUserService
            auth_svc = AuthUserService(s3_client)
            auth_user = auth_svc.find_by_id(user_id)
            if auth_user and auth_user.get("org_id"):
                return auth_user["org_id"]
        except Exception:
            pass

    if "@" not in email:
        return None

    from app.etl.s3.services.operational_service import OperationalService
    svc = OperationalService(s3_client)

    # Try domain lookup
    domain = email.split("@")[1].strip().lower()
    found = svc.get_org_by_domain(domain)
    if found:
        return found

    # Fallback: scan orgs matching email domain
    all_orgs = svc.get_all_organizations(include_system_counts=False)
    for org in all_orgs:
        org_email = (org.get("email") or "").lower()
        if "@" in org_email and org_email.split("@")[1] == domain:
            return org.get("org_id")

    return None


@router.get("/board", summary="Pipeline board — filtered by caller role and scope")
async def get_board(
    scope: Optional[str] = Query(None, description="all | aict | firm | individual"),
    scope_org_id: Optional[str] = Query(None, description="Firm/individual org_id to filter by"),
    org_id: Optional[str] = Query(None, description="Explicit org_id override for firm/individual users"),
    user: dict = Depends(require_permission("pipeline.view")),
):
    svc = _svc()
    user_org_id = org_id or _resolve_org_id(user)
    items = svc.get_board(
        user_role=user["role"],
        user_id=user["id"],
        user_org_id=user_org_id,
        scope=scope,
        scope_org_id=scope_org_id,
    )
    return {
        "stages": {s.value: STAGE_LABELS[s] for s in STAGE_ORDER},
        "stage_order": [s.value for s in STAGE_ORDER],
        "items": items,
        "total": len(items),
    }


@router.get("/board/filters", summary="Available board filter options (AICT admin)")
async def get_board_filters(
    user: dict = Depends(require_permission("pipeline.view")),
):
    """Return firms and individuals as filter options for AICT admin."""
    tier = user["role"].rsplit("_", 1)[0] if "_" in user["role"] else user["role"]
    if tier != "aict":
        return {"filters": []}

    from app.etl.s3.services.operational_service import OperationalService
    svc = OperationalService(s3_client)
    all_orgs = svc.get_all_organizations(include_system_counts=False)

    filters = [
        {"value": "all", "label": "All Organizations", "type": "all"},
        {"value": "aict", "label": "AICT Direct Clients", "type": "aict"},
    ]

    firms = [o for o in all_orgs if (o.get("onboarded_by_type") or "") == "firm"]
    for f in firms:
        filters.append({
            "value": f["org_id"],
            "label": f.get("name", f["org_id"]),
            "type": "firm",
        })

    individuals = [o for o in all_orgs if (o.get("onboarded_by_type") or "") == "individual"]
    for i in individuals:
        filters.append({
            "value": i["org_id"],
            "label": i.get("name", i["org_id"]),
            "type": "individual",
        })

    return {"filters": filters}


# ── Create / Init pipeline record ───────────────────────────────────────────


@router.post("/init", summary="Initialize a pipeline record for an assessment")
async def init_pipeline(
    body: SubmitAssessmentBody,
    user: dict = Depends(require_permission("pipeline.view")),
):
    svc = _svc()
    rec = svc.ensure_record(
        body.org_id,
        body.audit_id,
        body.project_id,
        body.ai_system_id,
    )
    return {"pipeline": rec}


# ── Submit assessment (practitioner) ─────────────────────────────────────────


@router.post("/submit-assessment", summary="Practitioner submits assessment — triggers gap analysis")
async def submit_assessment(
    body: SubmitAssessmentBody,
    user: dict = Depends(require_permission("assessment.fill")),
):
    def _do_submit():
        """All S3 I/O runs in a thread so the async event loop is not blocked."""
        svc = _svc()
        answer_svc = AnswerService(s3_client)

        # Fetch all answers for the scope
        answers = answer_svc.get_all_answers(
            org_id=body.org_id,
            audit_id=body.audit_id,
            project_id=body.project_id,
            ai_system_id=body.ai_system_id,
        )

        if not answers:
            return None  # signal: no answers

        question_ids = [a["question_id"] for a in answers if a.get("question_id")]

        # Bulk-update all answers to "submitted" in one pass
        submitted_count = answer_svc.bulk_set_state(
            org_id=body.org_id,
            audit_id=body.audit_id,
            project_id=body.project_id,
            ai_system_id=body.ai_system_id,
            answers=answers,
            new_state="submitted",
        )

        now = utc_now()

        # Transition pipeline: In Progress → AI Gap Analysis
        rec = svc.transition_stage(
            body.org_id,
            PipelineStage.AI_GAP_ANALYSIS,
            body.audit_id,
            body.project_id,
            body.ai_system_id,
            submitted_at=now,
            gap_analysis_status=GapAnalysisStatus.PENDING.value,
            gap_analysis_total=len(question_ids),
            gap_analysis_completed=0,
            gap_analysis_progress=0,
            answered_questions=submitted_count,
            total_questions=len(question_ids),
        )

        # Update org profile stage
        try:
            from app.etl.s3.services.operational_service import OperationalService
            org_svc = OperationalService(s3_client)
            org_svc.merge_org_profile(body.org_id, {"stage": PipelineStage.AI_GAP_ANALYSIS.value})
        except Exception as e:
            logger.warning("Failed to update org stage: %s", e)

        # Dispatch Celery task for gap analysis
        try:
            from app.pipeline.tasks import run_gap_analysis
            task = run_gap_analysis.delay(
                org_id=body.org_id,
                audit_id=body.audit_id,
                project_id=body.project_id,
                ai_system_id=body.ai_system_id,
                question_ids=question_ids,
            )
            rec["gap_analysis_task_id"] = task.id
            rec["gap_analysis_status"] = GapAnalysisStatus.RUNNING.value
            rec["gap_analysis_started_at"] = now
            svc.upsert_record(rec)
            logger.info("Gap analysis task dispatched: %s for org=%s", task.id, body.org_id)
        except Exception as e:
            logger.error("Failed to dispatch gap analysis task: %s", e)
            rec["gap_analysis_status"] = GapAnalysisStatus.FAILED.value
            svc.upsert_record(rec)

        return {"submitted_count": submitted_count, "pipeline": rec}

    # Run all blocking S3/Redis I/O off the event loop
    result = await asyncio.to_thread(_do_submit)

    if result is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_ANSWERS", "message": "No answers found to submit"},
        )

    return {
        "status": True,
        "message": f"Assessment submitted. {result['submitted_count']} answers locked. Gap analysis initiated.",
        "pipeline": result["pipeline"],
    }


# ── Status & Progress ───────────────────────────────────────────────────────


@router.get("/status", summary="Get pipeline status for an assessment")
async def get_status(
    org_id: str = Query(...),
    audit_id: str = Query(...),
    project_id: str = Query(..., min_length=3, max_length=3),
    ai_system_id: str = Query(..., min_length=4, max_length=4),
    user: dict = Depends(require_permission("pipeline.view")),
):
    svc = _svc()
    rec = svc.get_record(org_id, audit_id, project_id, ai_system_id)
    if not rec:
        return {"pipeline": None, "exists": False}
    return {"pipeline": rec, "exists": True}


@router.get("/gap-progress", summary="Get gap analysis progress")
async def get_gap_progress(
    org_id: str = Query(...),
    audit_id: str = Query(...),
    project_id: str = Query(..., min_length=3, max_length=3),
    ai_system_id: str = Query(..., min_length=4, max_length=4),
    user: dict = Depends(require_permission("pipeline.view")),
):
    svc = _svc()
    rec = svc.get_record(org_id, audit_id, project_id, ai_system_id)
    if not rec:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"message": "Pipeline record not found"})

    # Check Celery task status if available
    task_id = rec.get("gap_analysis_task_id")
    celery_status = None
    if task_id:
        try:
            from app.pipeline.celery_app import celery_app
            result = celery_app.AsyncResult(task_id)
            celery_status = result.status
        except Exception:
            pass

    return {
        "org_id": org_id,
        "audit_id": audit_id,
        "project_id": project_id,
        "ai_system_id": ai_system_id,
        "stage": rec.get("stage"),
        "gap_analysis_status": rec.get("gap_analysis_status"),
        "gap_analysis_progress": rec.get("gap_analysis_progress", 0),
        "gap_analysis_total": rec.get("gap_analysis_total", 0),
        "gap_analysis_completed": rec.get("gap_analysis_completed", 0),
        "celery_task_status": celery_status,
    }


# ── Gap report ──────────────────────────────────────────────────────────────


def _verify_gap_access(user: dict, org_id: str):
    """Verify the user has access to view this org's gap report.

    - AICT admin/manager: can view any approved org
    - Firm admin/manager: can view only their firm's clients
    - Individual admin/manager: can view only their own org
    """
    tier = user["role"].rsplit("_", 1)[0] if "_" in user["role"] else user["role"]

    if tier == "aict":
        # AICT can only view approved clients
        from app.etl.s3.services.operational_service import OperationalService
        org = OperationalService(s3_client).get_org_profile_raw(org_id)
        if not org or not org.get("aict_approved"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={"message": "Gap report only available for approved organizations"},
            )
        return

    if tier == "firm":
        user_org_id = _resolve_org_id(user)
        if not user_org_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"message": "Cannot resolve firm"})
        from app.etl.s3.services.operational_service import OperationalService
        org = OperationalService(s3_client).get_org_profile_raw(org_id)
        if not org or org.get("onboarded_by_id") != user_org_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={"message": "You can only view gap reports for your firm's clients"},
            )
        return

    if tier == "individual":
        user_org_id = _resolve_org_id(user)
        if org_id != user_org_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={"message": "You can only view your own gap report"},
            )
        return

    raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"message": "Access denied"})


@router.get("/gap-report", summary="Get completed gap analysis report")
async def get_gap_report(
    org_id: str = Query(...),
    audit_id: str = Query(...),
    project_id: str = Query(..., min_length=3, max_length=3),
    ai_system_id: str = Query(..., min_length=4, max_length=4),
    user: dict = Depends(require_permission("gap_analysis.view")),
):
    _verify_gap_access(user, org_id)
    svc = _svc()
    report = await asyncio.to_thread(svc.get_gap_report, org_id, audit_id, project_id, ai_system_id)
    if not report:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"message": "Gap report not found"})
    return {"report": report}


@router.get("/gap-report/question/{question_id}", summary="Get gap analysis for a specific question")
async def get_gap_question(
    question_id: str,
    org_id: str = Query(...),
    audit_id: str = Query(...),
    project_id: str = Query(..., min_length=3, max_length=3),
    ai_system_id: str = Query(..., min_length=4, max_length=4),
    user: dict = Depends(require_permission("gap_analysis.view")),
):
    _verify_gap_access(user, org_id)
    svc = _svc()
    result = svc.get_gap_question_result(org_id, audit_id, question_id, project_id, ai_system_id)
    if not result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"message": "Gap question result not found"})
    return {"result": result}


GAP_REPORTS_INDEX_KEY = "indexes/gap_reports_index.json"


def _update_gap_index(s3, entry: dict):
    """Add/update an entry in the global gap reports index.

    Stores org profile fields (name, approved, onboarded_by_type, onboarded_by_id)
    directly in the index so the /available endpoint needs only 1 S3 read.
    """
    from app.etl.s3.utils.s3_paths import org_profile_key

    data = s3.read_json(GAP_REPORTS_INDEX_KEY) or {"reports": []}
    reports = data.get("reports", [])

    # Enrich with org profile
    profile = s3.read_json(org_profile_key(entry["org_id"])) or {}
    entry["org_name"] = profile.get("name", entry.get("org_name", entry["org_id"]))
    entry["aict_approved"] = profile.get("aict_approved", False)
    entry["onboarded_by_type"] = profile.get("onboarded_by_type", "")
    entry["onboarded_by_id"] = profile.get("onboarded_by_id", "")
    entry["stage"] = profile.get("stage", "")

    key = f"{entry['org_id']}|{entry.get('audit_id', '')}|{entry['project_id']}|{entry['ai_system_id']}"
    reports = [
        r
        for r in reports
        if f"{r.get('org_id')}|{r.get('audit_id', '')}|{r.get('project_id')}|{r.get('ai_system_id')}"
        != key
    ]
    reports.append(entry)

    data["reports"] = reports
    s3.write_json(GAP_REPORTS_INDEX_KEY, data)


@router.get("/gap-report/available", summary="List orgs with gap reports available for this user")
async def list_available_gap_reports(
    user: dict = Depends(require_permission("gap_analysis.view")),
):
    """Return orgs with completed gap analysis, scoped by user role.

    Single S3 read from pre-built index. No per-org profile lookups.
    """
    tier = user["role"].rsplit("_", 1)[0] if "_" in user["role"] else user["role"]

    # AICT doesn't need org resolution — they see all approved
    user_org_id = None if tier == "aict" else _resolve_org_id(user)

    # Single read
    data = s3_client.read_json(GAP_REPORTS_INDEX_KEY) or {"reports": []}
    all_reports = data.get("reports", [])

    results = []
    for entry in all_reports:
        oid = entry.get("org_id", "")

        if tier == "aict":
            if not entry.get("aict_approved"):
                continue
        elif tier == "firm":
            if not user_org_id or entry.get("onboarded_by_id") != user_org_id:
                continue
        elif tier == "individual":
            if oid != user_org_id:
                continue
        else:
            continue

        results.append(entry)

    return {"organizations": results, "total": len(results)}


# ── Manual stage transitions (admin) ────────────────────────────────────────


@router.post("/transition", summary="Manually transition pipeline stage (admin)")
async def manual_transition(
    org_id: str = Query(...),
    audit_id: str = Query(...),
    stage: str = Query(...),
    project_id: str = Query(..., min_length=3, max_length=3),
    ai_system_id: str = Query(..., min_length=4, max_length=4),
    user: dict = Depends(require_permission("pipeline.view")),
):
    try:
        new_stage = PipelineStage(stage)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"message": f"Invalid stage: {stage}. Valid: {[s.value for s in STAGE_ORDER]}"},
        )

    svc = _svc()
    rec = svc.transition_stage(org_id, new_stage, audit_id, project_id, ai_system_id)

    try:
        from app.etl.s3.services.operational_service import OperationalService
        OperationalService(s3_client).merge_org_profile(org_id, {"stage": new_stage.value})
    except Exception as e:
        logger.warning("Failed to sync org stage: %s", e)

    return {"pipeline": rec}
