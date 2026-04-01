"""Assessment API: categories, questions, answers, evaluation, audit views, reviews."""

import logging

from fastapi import APIRouter, HTTPException, Query, status

from app.etl.s3.services.answer_service import AnswerService
from app.etl.s3.services.auditor_service import AuditorService
from app.etl.s3.services.report_service import ReportService
from app.procs.anchor_match.question_evaluator import QuestionEvaluator
from app.procs.anchor_match.question_faiss_index import QuestionFaissIndex
from app.procs.anchor_match.question_registry import QuestionRegistry
from app.procs.category_question_loader import CategoryQuestionLoader
from app.procs.embeddings import EmbeddingModel
from app.rest.deps import data_dir, s3_client
from app.rest.v1.assessment_schemas import (
    EvaluateAnswerBody,
    SaveAnswerBody,
    SaveReviewBody,
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
    return {
        "category_id": category,
        "questions": loader.load_category(category),
    }


@router.post("/evaluate-answer", summary="Evaluate a user answer (FAISS + rubric)")
async def evaluate_answer(body: EvaluateAnswerBody):
    if not data_dir:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONFIG", "message": "data_dir is not configured"},
        )
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
    registry = QuestionRegistry(data_dir)
    try:
        AnswerService(s3_client).upsert_answer(
            org_id=body.org_id,
            audit_id=0,
            question_id=body.question_id,
            answer=body.user_answer,
            state=body.state,
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "SAVE_ANSWER_FAILED", "message": str(e)},
        ) from e
    return {
        "status": True,
        "saved_to": "s3",
        "question_path": registry.get_question_path(body.question_id),
    }


@router.get("/answers", summary="Fetch all answers for an org (fixed audit_id=0 server-side)")
async def fetch_answers(
    org_id: str = Query(...),
    audit_id: str = Query("0", description="Echoed for clients; storage may still use 0"),
):
    try:
        answers = AnswerService(s3_client).get_all_answers(org_id=org_id, audit_id=0)
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "FETCH_ANSWERS_FAILED", "message": str(e)},
        ) from e
    answers_map = {item["question_id"]: item for item in answers}
    return {
        "org_id": org_id,
        "audit_id": audit_id,
        "total": len(answers_map),
        "answers": answers_map,
    }


@router.get(
    "/orgs/{org_id}/audit-view",
    summary="Full audit / gap snapshot (same backing as legacy FETCH-FULL-AUDIT)",
)
async def get_audit_view(org_id: str, audit_id: str = Query("0")):
    try:
        result = ReportService(s3_client).get_full_audit_view(org_id, audit_id)
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "AUDIT_VIEW_FAILED", "message": str(e)},
        ) from e
    return {"org_id": org_id, "audit_id": audit_id, "status": True, **result}


@router.post("/reviews", summary="Save auditor feedback for a question answer")
async def save_review(body: SaveReviewBody):
    if not all([body.org_id, body.audit_id, body.question_id, body.review_state]):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION", "message": "org_id, audit_id, question_id, review_state required"},
        )
    answer_service = AnswerService(s3_client)
    auditor_service = AuditorService(s3_client)
    answer = answer_service.get_answer(body.org_id, body.audit_id, body.question_id)
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
        "review_state": body.review_state,
        "summary": body.reviewer_comment,
        "feedback": [],
    }
    try:
        result = auditor_service.update_feedback(
            org_id=body.org_id,
            audit_id=body.audit_id,
            question_id=body.question_id,
            feedback=feedback_payload,
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
