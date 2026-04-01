from app.engine.emitter import EventEmitter
from app.engine.message_router import route
from app.handlers.common import data_dir
from app.procs.category_question_loader import CategoryQuestionLoader


@route("AI-ASSESSMENT-REQ", "GET-CATEGORIES")
async def get_assessment_categories(ws, client_id, request, manager):
    emitter = EventEmitter(websocket=ws)
    await emitter.info(
        "💬 Connected (Context: AI Assessment)",
        payload={"data_dir": data_dir},
    )

    if not data_dir:
        await emitter.error("🚩 Missing data_dir")
        return

    category_question_loader = CategoryQuestionLoader(data_dir)

    await emitter.info(
        "🧱 Assessment Categories",
        payload={
            "reqType": request.reqType,
            "reqSubType": request.reqSubType,
            "Categories": category_question_loader.list_categories(),
        },
    )
