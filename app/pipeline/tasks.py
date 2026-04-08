"""Celery task implementations for the assessment pipeline.

These run in a *worker* process (not inside uvicorn). The API enqueues them via
``.delay()`` so long-running work does not block HTTP.

Tasks defined here
    * ``pipeline.run_gap_analysis`` — Dispatched from ``app.pipeline.router``
      when an assessment is submitted. Reads answers from S3, runs per-question
      gap analysis (LLM / analyzer), updates pipeline progress, writes the gap
      report, refreshes gap index, org stage, and review queue. Task id is stored
      on the pipeline record as ``gap_analysis_task_id`` for progress UIs.
    * ``pipeline.recompute_derived_audit`` — Dispatched from
      ``app.etl.s3.services.derived_service.schedule_derived_recompute`` (audit
      lifecycle). Writes ``derived/*`` placeholder JSON in S3; replace with real
      metrics/LLM later. If Celery is unavailable, callers fall back to sync stub.

Environment
    Same as the API: ``get_config()``, S3 bucket, category data dir, and any
    keys required by ``analyze_question`` must be valid in the worker container.

See also
    ``app.pipeline.celery_app`` and ``app/pipeline/README.md``.
"""

import logging
from typing import List

from dotenv import load_dotenv

load_dotenv()

from app.pipeline.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="pipeline.run_gap_analysis", max_retries=2)
def run_gap_analysis(
    self,
    org_id: str,
    audit_id: str,
    project_id: str,
    ai_system_id: str,
    question_ids: List[str] = None,
):
    """Run gap analysis for all submitted questions in an assessment.

    For each question:
    1. Fetch the saved answer from S3
    2. Fetch the question text from the category loader
    3. Run semantic search + LLM gap analysis
    4. Save per-question result to S3
    5. Update pipeline progress

    On completion, saves full gap report and transitions to Under Review.
    """
    from app.config import get_config
    from app.etl.s3.services.s3_client import S3Client
    from app.etl.s3.services.answer_service import AnswerService
    from app.pipeline.service import PipelineService
    from app.pipeline.models import GapAnalysisStatus, PipelineStage
    from app.pipeline.gap_analysis.analyzer import analyze_question
    from app.procs.category_question_loader import CategoryQuestionLoader

    cfg = get_config()
    s3 = S3Client(bucket=cfg.ai_assessment.s3.bucket)
    pipeline_svc = PipelineService(s3)
    answer_svc = AnswerService(s3)

    question_ids = question_ids or []
    total = len(question_ids)
    logger.info("Starting gap analysis for org=%s, %d questions", org_id, total)

    # Update status to running
    pipeline_svc.transition_stage(
        org_id,
        PipelineStage.AI_GAP_ANALYSIS,
        audit_id,
        project_id,
        ai_system_id,
        gap_analysis_status=GapAnalysisStatus.RUNNING.value,
    )

    # Build question text lookup from category loader
    loader = CategoryQuestionLoader(cfg.ai_assessment.data_dir)
    question_map = {}
    for cat in loader.list_categories():
        cat_id = cat.get("category_id", "")
        cat_data = loader.load_category(cat_id)
        questions = cat_data.get("questions", []) if isinstance(cat_data, dict) else cat_data
        for q in questions:
            qid = q.get("question_id", "")
            question_map[qid] = {
                "text": q.get("question", q.get("text", "")),
                "category_id": cat_id,
            }

    results = []
    completed = 0

    for qid in question_ids:
        try:
            # Get saved answer
            answer_data = answer_svc.get_answer(
                org_id=org_id,
                audit_id=audit_id,
                question_id=qid,
                project_id=project_id,
                ai_system_id=ai_system_id,
            )

            user_answer = ""
            if answer_data:
                user_answer = answer_data.get("answer", "")

            if not user_answer:
                logger.warning("No answer found for q=%s, skipping", qid)
                completed += 1
                pipeline_svc.update_gap_progress(
                    org_id,
                    audit_id,
                    project_id,
                    ai_system_id,
                    completed=completed,
                    total=total,
                )
                continue

            # Get question text
            q_info = question_map.get(qid, {})
            question_text = q_info.get("text", f"Question {qid}")
            category_id = q_info.get("category_id", "")

            # Run analysis
            result = analyze_question(
                question_text=question_text,
                user_answer=user_answer,
                question_id=qid,
                category_id=category_id,
            )

            # Save per-question result
            pipeline_svc.save_gap_question_result(
                org_id, audit_id, qid, result, project_id, ai_system_id,
            )

            results.append(result)
            completed += 1

            # Update progress
            pipeline_svc.update_gap_progress(
                org_id,
                audit_id,
                project_id,
                ai_system_id,
                completed=completed,
                total=total,
            )

            logger.info("Gap analysis completed for q=%s (%d/%d)", qid, completed, total)

        except Exception as e:
            logger.error("Gap analysis failed for q=%s: %s", qid, e)
            completed += 1
            results.append({
                "question_id": qid,
                "status": "error",
                "error": str(e),
                "match_score": 0.0,
            })
            pipeline_svc.update_gap_progress(
                org_id,
                audit_id,
                project_id,
                ai_system_id,
                completed=completed,
                total=total,
            )

    # Save full gap report
    avg_score = 0.0
    scored = [r for r in results if isinstance(r.get("match_score"), (int, float))]
    if scored:
        avg_score = sum(r["match_score"] for r in scored) / len(scored)

    report = {
        "org_id": org_id,
        "project_id": project_id,
        "ai_system_id": ai_system_id,
        "audit_id": audit_id,
        "total_questions": total,
        "analyzed_count": len(results),
        "average_match_score": round(avg_score, 3),
        "questions": results,
    }

    pipeline_svc.save_gap_report(org_id, audit_id, report, project_id, ai_system_id)

    # Update gap reports index for fast listing
    try:
        from app.pipeline.router import _update_gap_index
        from app.etl.s3.utils.s3_paths import system_json_key
        sys_doc = s3.read_json(system_json_key(org_id, project_id, ai_system_id)) or {}
        _update_gap_index(s3, {
            "org_id": org_id,
            "audit_id": audit_id,
            "ai_system_id": ai_system_id,
            "ai_system_name": sys_doc.get("name", ai_system_id),
            "project_id": project_id,
        })
    except Exception as e:
        logger.warning("Failed to update gap index: %s", e)

    # Update org profile stage to under_review
    try:
        from app.etl.s3.services.operational_service import OperationalService
        OperationalService(s3).merge_org_profile(org_id, {"stage": PipelineStage.UNDER_REVIEW.value})
    except Exception as e:
        logger.warning("Failed to update org stage: %s", e)

    # Create review queue entry so CSAP desk/review page shows this assessment
    try:
        from app.etl.s3.services.review_service import ReviewService
        from app.etl.s3.services.operational_service import OperationalService as _OpSvc
        review_svc = ReviewService(s3)
        org_profile = _OpSvc(s3).get_org_profile_raw(org_id) or {}
        review_svc._upsert_index_entry(org_id, {
            "status": "in_review",
            "org_id": org_id,
            "org_name": org_profile.get("name", ""),
            "audit_id": audit_id,
            "project_id": project_id,
            "ai_system_id": ai_system_id,
            "total_questions": total,
            "gap_analysis_score": round(avg_score, 3),
        })
        logger.info("Created review queue entry for org=%s", org_id)
    except Exception as e:
        logger.warning("Failed to create review queue entry: %s", e)

    logger.info(
        "Gap analysis complete for org=%s: %d questions, avg_score=%.3f",
        org_id, total, avg_score,
    )

    return {
        "org_id": org_id,
        "total": total,
        "completed": len(results),
        "average_match_score": round(avg_score, 3),
    }


@celery_app.task(name="pipeline.recompute_derived_audit")
def recompute_derived_audit_task(
    org_id: str,
    audit_id: str,
    project_id: str,
    ai_system_id: str,
):
    """Write placeholder derived/* bundle (replace with real metrics pipeline later)."""
    from app.config import get_config
    from app.etl.s3.services.derived_service import DerivedAuditService
    from app.etl.s3.services.s3_client import S3Client

    cfg = get_config()
    s3 = S3Client(bucket=cfg.ai_assessment.s3.bucket)
    return DerivedAuditService(s3).write_placeholder_bundle(
        org_id, audit_id, project_id, ai_system_id
    )
