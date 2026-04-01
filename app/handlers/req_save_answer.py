from app.engine.emitter import EventEmitter
from app.engine.message_router import route
from app.etl.s3.services.answer_service import AnswerService
from app.handlers.common import data_dir, s3_client
from app.procs.anchor_match.question_registry import QuestionRegistry


@route("AI-ASSESSMENT-REQ", "SAVE-ANSWER")
async def save_answer(ws, client_id, request, manager):
    emitter = EventEmitter(websocket=ws)

    reqData = request.reqData

    if not reqData:
        await emitter.error("🚩 Missing 'reqData' field")
        return

    org_id = reqData.get("org_id", "0")
    q_id = reqData.get("question_id", "")
    user_answer = reqData.get("user_answer", "")
    state = reqData.get("state", "draft")

    if not all([q_id, user_answer, org_id, state]):
        await emitter.error(
            "🚩 The payload 'reqData must contain non-empty: question_id, user_answer; "
            "org_id and state default to '0' and 'draft' when omitted"
        )
        return

    question_registry = QuestionRegistry(data_dir)

    try:
        answer_service = AnswerService(s3_client)

        answer_service.upsert_answer(
            org_id=org_id,
            audit_id=0,
            question_id=q_id,
            answer=user_answer,
            state=state,
        )

        await emitter.info(
            "🧱 Save Answer",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "question_path": question_registry.get_question_path(q_id),
                "status": True,
                "saved_to": "s3",
            },
        )

    except Exception as e:
        await emitter.error(
            f"❌ Failed to save answer: {str(e)}",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
            },
        )
