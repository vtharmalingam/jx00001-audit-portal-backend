"""CSAP review API: per-question opinions, category verdicts, final attestations."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.permissions import require_permission
from app.etl.s3.services.review_service import ReviewService, VALID_OPINIONS, VALID_VERDICTS
from app.rest.deps import s3_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/review", tags=["review"])


def _svc() -> ReviewService:
    return ReviewService(s3_client)


# ── Request schemas ──────────────────────────────────────────────────────────

class OpinionBody(BaseModel):
    question_id: str = Field(..., description="Question being reviewed")
    opinion: str = Field(..., description="clean | qualified | adverse | disclaimer")
    note: Optional[str] = Field(None, description="Optional reviewer note")


class VerdictBody(BaseModel):
    category_id: str = Field(..., description="Category being judged")
    verdict: str = Field(..., description="pass | fail")
    note: Optional[str] = Field(None, description="Optional justification")


class AttestationBody(BaseModel):
    attestation: str = Field(..., description="clean | qualified | adverse | disclaimer")
    justification: Optional[str] = Field(None, description="Reason for the attestation")


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/queue", summary="List all reviews (CSAP review queue)")
async def list_reviews(user: dict = Depends(require_permission("review.opinion"))):
    svc = _svc()
    return {"reviews": svc.list_reviews()}


@router.get("/{project_id}", summary="Get full review for a project")
async def get_review(
    project_id: str,
    user: dict = Depends(require_permission("review.opinion")),
):
    svc = _svc()
    return {"review": svc.get_review(project_id)}


@router.post("/{project_id}/opinion", summary="Save per-question opinion")
async def save_opinion(
    project_id: str,
    body: OpinionBody,
    user: dict = Depends(require_permission("review.opinion")),
):
    svc = _svc()
    try:
        review = svc.save_opinion(
            project_id=project_id,
            question_id=body.question_id,
            opinion=body.opinion,
            csap_user_id=user["id"],
            note=body.note,
        )
        return {"review": review}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": str(e)})


@router.post("/{project_id}/verdict", summary="Save per-category verdict")
async def save_verdict(
    project_id: str,
    body: VerdictBody,
    user: dict = Depends(require_permission("review.verdict")),
):
    svc = _svc()
    try:
        review = svc.save_verdict(
            project_id=project_id,
            category_id=body.category_id,
            verdict=body.verdict,
            csap_user_id=user["id"],
            note=body.note,
        )
        return {"review": review}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": str(e)})


@router.post("/{project_id}/attestation", summary="Issue final project attestation")
async def save_attestation(
    project_id: str,
    body: AttestationBody,
    user: dict = Depends(require_permission("review.attestation")),
):
    svc = _svc()
    try:
        review = svc.save_attestation(
            project_id=project_id,
            attestation=body.attestation,
            csap_user_id=user["id"],
            justification=body.justification,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": str(e)})

    # Transition pipeline → Review Complete and sync org stage
    # project_id in the review URL is the org_id
    try:
        from app.pipeline.service import PipelineService
        from app.pipeline.models import PipelineStage
        from app.etl.s3.services.operational_service import OperationalService
        from app.etl.s3.utils.helpers import utc_now

        pipe_svc = PipelineService(s3_client)
        org_svc = OperationalService(s3_client)
        org_id = project_id  # review uses org_id as project_id

        # Find all AI systems for this org and transition each
        systems = org_svc.list_ai_systems(org_id)
        transitioned = False
        for sys in (systems or []):
            sid = str(sys.get("system_id") or sys.get("ai_system_id") or "")
            pid = str(sys.get("project_id") or "")
            audit_id = str(sys.get("audit_id") or "")
            if len(pid) != 3 or len(sid) != 4 or len(audit_id) != 26:
                continue
            pipe_svc.transition_stage(
                org_id,
                PipelineStage.REVIEW_COMPLETE,
                audit_id,
                pid,
                sid,
                review_completed_at=utc_now(),
            )
            transitioned = True
        org_svc.merge_org_profile(org_id, {"stage": PipelineStage.REVIEW_COMPLETE.value})
    except Exception as e:
        logger.warning("Pipeline transition to review_complete failed: %s", e)

    return {"review": review}


@router.get("/{project_id}/trust-score", summary="Get trust score and suggested attestation")
async def get_trust_score(
    project_id: str,
    user: dict = Depends(require_permission("review.opinion")),
):
    svc = _svc()
    return svc.get_trust_score(project_id)
