from app.engine.emitter import EventEmitter
from app.engine.message_router import route
from app.handlers.common import data_dir
from app.procs.category_question_loader import CategoryQuestionLoader


@route("AI-ASSESSMENT-REQ", "GET-QUESTIONS")
async def get_questions_by_category(ws, client_id, request, manager):
    emitter = EventEmitter(websocket=ws)
    await emitter.info(
        "💬 Connected (Context: AI Assessment)",
        payload={"data_dir": data_dir},
    )

    reqData = request.reqData

    if not reqData:
        await emitter.error("🚩 Missing 'reqData' field")
        return

    category = reqData.get("category", "")

    if not all([category]):
        await emitter.error("🚩 The payload 'reqData must contain these: category'")
        return

    category_question_loader = CategoryQuestionLoader(data_dir)

    await emitter.info(
        "🧱 Questions",
        payload={
            "reqType": request.reqType,
            "reqSubType": request.reqSubType,
            "Questions": category_question_loader.load_category(category),
        },
    )
