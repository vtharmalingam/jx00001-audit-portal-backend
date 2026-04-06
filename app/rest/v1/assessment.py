"""Assessment API: categories, questions, answers, evaluation, audit views, reviews."""

import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.permissions import require_permission

from app.etl.s3.services.answer_service import AnswerService
from app.etl.s3.services.auditor_service import AuditorService
from app.etl.s3.services.evidence_service import EvidenceService
from app.etl.s3.services.report_service import ReportService
from app.procs.category_question_loader import CategoryQuestionLoader
from app.rest.deps import data_dir, s3_client
from app.rest.strict_audit_ids import enforce_strict_audit_scope
from app.rest.v1.assessment_schemas import (
    CreateCategoryBody,
    CreateQuestionBody,
    EvaluateAnswerBody,
    EvidenceRegisterBody,
    SaveAnswerBody,
    SaveReviewBody,
    UpdateCategoryBody,
    UpdateQuestionBody,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assessment", tags=["assessment"])


@router.get("/categories", summary="List assessment categories")
async def list_categories():
    if not data_dir:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONFIG", "message": "data_dir is not configured"},
        )
    loader = CategoryQuestionLoader(data_dir)
    return {"categories": loader.list_categories()}


@router.get("/questions", summary="Load questions for a category")
async def list_questions(category: str = Query(..., description="Category id")):
    if not data_dir:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONFIG", "message": "data_dir is not configured"},
        )
    loader = CategoryQuestionLoader(data_dir)
    result = loader.load_category(category)
    return {
        "category_id": category,
        "questions": result.get("questions", []) if isinstance(result, dict) else result,
    }


@router.post("/evaluate-answer", summary="Evaluate a user answer (FAISS + rubric) [legacy]")
async def evaluate_answer(body: EvaluateAnswerBody):
    if not data_dir:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONFIG", "message": "data_dir is not configured"},
        )
    try:
        from app.procs.embeddings import EmbeddingModel
        from app.procs.anchor_match.question_evaluator import QuestionEvaluator
        from app.procs.anchor_match.question_faiss_index import QuestionFaissIndex
        from app.procs.anchor_match.question_registry import QuestionRegistry
    except ImportError as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "LEGACY_DEPS", "message": f"Legacy dependencies not installed: {e}"},
        ) from e
    embedder = EmbeddingModel()
    registry = QuestionRegistry(data_dir)
    index = QuestionFaissIndex(body.q_id, embedder, registry)
    if index.exists():
        index.load()
    else:
        logger.warning("No FAISS index for question_id=%s (not building automatically)", body.q_id)

    evaluator = QuestionEvaluator(body.q_id, embedding_model=embedder, registry=registry)
    assessment = evaluator.evaluate(body.user_answer)
    return {"assessment": assessment, "q_id": body.q_id}


@router.post("/answers", summary="Upsert an answer (S3)")
async def save_answer(body: SaveAnswerBody):
    if not all([body.question_id, body.user_answer, body.org_id, body.state]):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION", "message": "question_id, user_answer, org_id, state required"},
        )
    enforce_strict_audit_scope(
        body.org_id,
        str(body.audit_id),
        project_id=str(body.project_id),
        ai_system_id=str(body.ai_system_id),
    )
    try:
        AnswerService(s3_client).upsert_answer(
            org_id=body.org_id,
            audit_id=str(body.audit_id),
            project_id=str(body.project_id),
            ai_system_id=str(body.ai_system_id),
            question_id=body.question_id,
            answer=body.user_answer,
            state=body.state,
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "SAVE_ANSWER_FAILED", "message": str(e)},
        ) from e

    # Auto-transition pipeline: Not Started → In Progress on first answer
    try:
        from app.pipeline.service import PipelineService
        from app.pipeline.models import PipelineStage
        from app.etl.s3.services.operational_service import OperationalService

        pipe_svc = PipelineService(s3_client)
        rec = pipe_svc.get_record(
            body.org_id,
            str(body.audit_id),
            str(body.project_id),
            str(body.ai_system_id),
        )
        current_stage = (rec or {}).get("stage", "not_started")

        if current_stage == PipelineStage.NOT_STARTED.value:
            pipe_svc.ensure_record(
                body.org_id,
                str(body.audit_id),
                str(body.project_id),
                str(body.ai_system_id),
                stage=PipelineStage.IN_PROGRESS.value,
            )
            OperationalService(s3_client).merge_org_profile(
                body.org_id, {"stage": PipelineStage.IN_PROGRESS.value}
            )
    except Exception as e:
        logger.warning("Pipeline auto-transition failed: %s", e)

    return {
        "status": True,
        "saved_to": "s3",
    }


@router.get("/answers", summary="Fetch all answers for an org / audit scope")
async def fetch_answers(
    org_id: str = Query(...),
    audit_id: str = Query(...),
    project_id: str = Query(..., min_length=3, max_length=3),
    ai_system_id: str = Query(..., min_length=4, max_length=4),
):
    enforce_strict_audit_scope(
        org_id,
        audit_id,
        project_id=project_id,
        ai_system_id=ai_system_id,
    )
    try:
        answers = AnswerService(s3_client).get_all_answers(
            org_id=org_id,
            audit_id=audit_id,
            project_id=project_id,
            ai_system_id=ai_system_id,
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "FETCH_ANSWERS_FAILED", "message": str(e)},
        ) from e
    answers_map = {item["question_id"]: item for item in answers}
    return {
        "org_id": org_id,
        "audit_id": audit_id,
        "project_id": project_id,
        "ai_system_id": ai_system_id,
        "total": len(answers_map),
        "answers": answers_map,
    }


@router.get(
    "/orgs/{org_id}/audit-view",
    summary="Full audit / gap snapshot",
)
async def get_audit_view(
    org_id: str,
    audit_id: str = Query(...),
    project_id: str = Query(..., min_length=3, max_length=3),
    ai_system_id: str = Query(..., min_length=4, max_length=4),
):
    enforce_strict_audit_scope(
        org_id,
        audit_id,
        project_id=project_id,
        ai_system_id=ai_system_id,
    )
    try:
        result = ReportService(s3_client).get_full_audit_view(
            org_id,
            audit_id,
            project_id=project_id,
            ai_system_id=ai_system_id,
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "AUDIT_VIEW_FAILED", "message": str(e)},
        ) from e
    return {
        "org_id": org_id,
        "audit_id": audit_id,
        "project_id": project_id,
        "ai_system_id": ai_system_id,
        "status": True,
        **result,
    }


@router.post(
    "/reviews",
    summary="Save auditor feedback for a question answer",
    dependencies=[Depends(require_permission("assessment.review"))],
)
async def save_review(body: SaveReviewBody):
    if not all([body.org_id, body.audit_id, body.question_id, body.review_state]):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION", "message": "org_id, audit_id, question_id, review_state required"},
        )
    enforce_strict_audit_scope(
        body.org_id,
        body.audit_id,
        project_id=body.project_id,
        ai_system_id=body.ai_system_id,
    )
    answer_service = AnswerService(s3_client)
    auditor_service = AuditorService(s3_client)
    answer = answer_service.get_answer(
        body.org_id,
        body.audit_id,
        body.question_id,
        project_id=body.project_id,
        ai_system_id=body.ai_system_id,
    )
    if not answer:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Answer not found for question"},
        )
    version = answer.get("version", 0)
    auditor_ref = body.auditor_id or "auditor_unknown"
    feedback_payload = {
        "version": version,
        "auditor_id": auditor_ref,
        "auditor_name": body.auditor_name,
        "review_state": body.review_state,
        "summary": body.reviewer_comment,
        "feedback": [],
        "recommendations": body.recommendations or [],
    }
    try:
        result = auditor_service.update_feedback(
            org_id=body.org_id,
            audit_id=body.audit_id,
            question_id=body.question_id,
            feedback=feedback_payload,
            project_id=body.project_id,
            ai_system_id=body.ai_system_id,
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "SAVE_REVIEW_FAILED", "message": str(e)},
        ) from e
    return {
        "status": True,
        "org_id": body.org_id,
        "audit_id": body.audit_id,
        "question_id": body.question_id,
        "review_state": result.get("review_state"),
        "reviewed_version": result.get("reviewed_version"),
    }


@router.post("/evidence", summary="Register evidence file (upload bytes or reference key)")
async def register_evidence(body: EvidenceRegisterBody):
    if not body.content_base64 and not body.s3_key_override:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VALIDATION",
                "message": "Provide content_base64 or s3_key_override",
            },
        )
    raw: Optional[bytes] = None
    if body.content_base64:
        try:
            raw = base64.b64decode(body.content_base64)
        except Exception as e:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_BASE64", "message": str(e)},
            ) from e
    enforce_strict_audit_scope(
        body.org_id,
        body.audit_id,
        project_id=body.project_id,
        ai_system_id=body.ai_system_id,
    )
    try:
        entry = EvidenceService(s3_client).register_evidence(
            body.org_id,
            body.audit_id,
            body.question_id,
            file_name=body.file_name,
            s3_key=body.s3_key_override,
            uploaded_by=body.uploaded_by,
            project_id=body.project_id,
            ai_system_id=body.ai_system_id,
            body=raw,
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "EVIDENCE_FAILED", "message": str(e)},
        ) from e
    return {"status": True, "evidence": entry}


@router.get("/evidence", summary="Fetch evidence entries for an audit scope")
async def fetch_evidence(
    org_id: str = Query(...),
    audit_id: str = Query(...),
    question_id: Optional[str] = Query(None),
    project_id: str = Query(..., min_length=3, max_length=3),
    ai_system_id: str = Query(..., min_length=4, max_length=4),
):
    enforce_strict_audit_scope(
        org_id,
        audit_id,
        project_id=project_id,
        ai_system_id=ai_system_id,
    )
    try:
        index = EvidenceService(s3_client).list_index(
            org_id,
            audit_id,
            project_id=project_id,
            ai_system_id=ai_system_id,
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "EVIDENCE_FETCH_FAILED", "message": str(e)},
        ) from e

    if question_id:
        items = index.get(question_id, [])
        return {
            "org_id": org_id,
            "audit_id": audit_id,
            "project_id": project_id,
            "ai_system_id": ai_system_id,
            "question_id": question_id,
            "total": len(items),
            "evidences": items,
        }

    total = sum(len(v) for v in index.values())
    return {
        "org_id": org_id,
        "audit_id": audit_id,
        "project_id": project_id,
        "ai_system_id": ai_system_id,
        "total": total,
        "evidence_index": index,
    }


# ── Category CRUD ──────────────────────────────────────────────────────────


@router.post(
    "/categories",
    summary="Create a new assessment category",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("library.manage"))],
)
async def create_category(body: CreateCategoryBody):
    if not data_dir:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONFIG", "message": "data_dir is not configured"},
        )
    loader = CategoryQuestionLoader(data_dir)
    try:
        cat = loader.create_category(body.category_id, body.display_name, body.description, control_id=body.control_id)
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "CREATE_CATEGORY_FAILED", "message": str(e)},
        ) from e
    return cat


@router.put(
    "/categories/{category_id}",
    summary="Update an assessment category",
    dependencies=[Depends(require_permission("library.manage"))],
)
async def update_category(category_id: str, body: UpdateCategoryBody):
    if not data_dir:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONFIG", "message": "data_dir is not configured"},
        )
    loader = CategoryQuestionLoader(data_dir)
    try:
        updates = body.model_dump(exclude_none=True)
        cat = loader.update_category(category_id, updates)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": str(e)}) from e
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "UPDATE_CATEGORY_FAILED", "message": str(e)},
        ) from e
    return cat


@router.delete(
    "/categories/{category_id}",
    summary="Delete an assessment category",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("library.manage"))],
)
async def delete_category(category_id: str):
    if not data_dir:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONFIG", "message": "data_dir is not configured"},
        )
    loader = CategoryQuestionLoader(data_dir)
    try:
        loader.delete_category(category_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": str(e)}) from e
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "DELETE_CATEGORY_FAILED", "message": str(e)},
        ) from e


# ── Question CRUD ──────────────────────────────────────────────────────────


@router.post(
    "/questions",
    summary="Create a new assessment question",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("library.manage"))],
)
async def create_question(body: CreateQuestionBody):
    if not data_dir:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONFIG", "message": "data_dir is not configured"},
        )
    loader = CategoryQuestionLoader(data_dir)
    try:
        q = loader.create_question(body.model_dump())
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": str(e)}) from e
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "CREATE_QUESTION_FAILED", "message": str(e)},
        ) from e
    return q


@router.put(
    "/questions/{question_id}",
    summary="Update an assessment question",
    dependencies=[Depends(require_permission("library.manage"))],
)
async def update_question(question_id: str, body: UpdateQuestionBody):
    if not data_dir:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONFIG", "message": "data_dir is not configured"},
        )
    loader = CategoryQuestionLoader(data_dir)
    try:
        updates = body.model_dump(exclude_none=True)
        q = loader.update_question(question_id, updates)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": str(e)}) from e
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "UPDATE_QUESTION_FAILED", "message": str(e)},
        ) from e
    return q


@router.delete(
    "/questions/{question_id}",
    summary="Delete an assessment question",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("library.manage"))],
)
async def delete_question(question_id: str):
    if not data_dir:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONFIG", "message": "data_dir is not configured"},
        )
    loader = CategoryQuestionLoader(data_dir)
    try:
        loader.delete_question(question_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": str(e)}) from e
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "DELETE_QUESTION_FAILED", "message": str(e)},
        ) from e
