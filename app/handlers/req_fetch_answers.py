from app.engine.emitter import EventEmitter
from app.engine.message_router import route
from app.etl.s3.services.answer_service import AnswerService
from app.handlers.common import s3_client


@route("AI-ASSESSMENT-REQ", "FETCH-ANSWERS")
async def fetch_answers(ws, client_id, request, manager):
    emitter = EventEmitter(websocket=ws)

    reqData = request.reqData

    if not reqData:
        await emitter.error("🚩 Missing 'reqData' field")
        return

    org_id = reqData.get("org_id")
    audit_id = reqData.get("audit_id", "0")

    if not org_id:
        await emitter.error("🚩 'org_id' is required")
        return

    try:
        answer_service = AnswerService(s3_client)

        answers = answer_service.get_all_answers(
            org_id=org_id,
            audit_id=0,
        )

        answers_map = {item["question_id"]: item for item in answers}

        await emitter.info(
            "📥 Fetch Answers",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "status": True,
                "org_id": org_id,
                "audit_id": audit_id,
                "total": len(answers_map),
                "answers": answers_map,
            },
        )

    except Exception as e:
        await emitter.error(
            f"❌ Failed to fetch answers: {str(e)}",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "org_id": org_id,
                "audit_id": audit_id,
            },
        )
