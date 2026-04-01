from app.engine.emitter import EventEmitter
from app.engine.message_router import route
from app.etl.s3.services.answer_service import AnswerService
from app.etl.s3.services.auditor_service import AuditorService
from app.handlers.common import s3_client


@route("AI-ASSESSMENT-REQ", "SAVE-REVIEW")
async def save_review(ws, client_id, request, manager):
    emitter = EventEmitter(websocket=ws)

    reqData = request.reqData

    if not reqData:
        await emitter.error("🚩 Missing 'reqData'")
        return

    org_id = reqData.get("org_id")
    audit_id = reqData.get("audit_id", "0")
    question_id = reqData.get("question_id")
    review_state = reqData.get("review_state")
    reviewer_comment = reqData.get("reviewer_comment")

    if not all([org_id, audit_id, question_id, review_state]):
        await emitter.error(
            "🚩 Required: org_id, audit_id, question_id, review_state"
        )
        return

    try:
        auditor_service = AuditorService(s3_client)
        answer_service = AnswerService(s3_client)

        answer = answer_service.get_answer(org_id, audit_id, question_id)

        if not answer:
            await emitter.error("❌ Answer not found for question")
            return

        version = answer.get("version", 0)

        feedback_payload = {
            "version": version,
            "auditor_id": client_id or "auditor_unknown",
            "review_state": review_state,
            "summary": reviewer_comment,
            "feedback": [],
        }

        result = auditor_service.update_feedback(
            org_id=org_id,
            audit_id=audit_id,
            question_id=question_id,
            feedback=feedback_payload,
        )

        await emitter.info(
            "🧑‍⚖️ Save Review",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "status": True,
                "org_id": org_id,
                "audit_id": audit_id,
                "question_id": question_id,
                "review_state": result.get("review_state"),
                "reviewed_version": result.get("reviewed_version"),
            },
        )

    except Exception as e:
        await emitter.error(
            f"❌ Failed to save review: {str(e)}",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "org_id": org_id,
                "audit_id": audit_id,
                "question_id": question_id,
            },
        )
