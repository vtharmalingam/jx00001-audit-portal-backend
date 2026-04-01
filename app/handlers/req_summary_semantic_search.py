from app.engine.emitter import EventEmitter
from app.engine.message_router import route
from app.handlers.common import engine


@route("SUPPORTWIZ_USER_REQS", "SUMMARY-SEMANTIC-SEARCH")
async def search_s_kbindex_by_context(
    ws,
    client_id,
    request,
    manager,
):
    """
    Semantic / similarity search on KB questions by context text.
    Optionally creates a cluster.
    """

    emitter = EventEmitter(websocket=ws)
    await emitter.info("💬 Connected (Context: SupportWiz)")

    reqData = request.reqData

    if not reqData:
        await emitter.error("🚩 Missing 'reqData' field")
        return

    QUERY = reqData.get("context", "")
    COUNT = reqData.get("count", 10)

    if not all([QUERY, COUNT]):
        await emitter.error(
            "🚩 The payload 'reqData must contain these: context (non-empty), count (≥ 1)"
        )
        return

    supportwiz_response = engine.semantic_summary(QUERY, COUNT)

    payload = {
        "reqType": request.reqType,
        "reqSubType": request.reqSubType,
    }

    if isinstance(supportwiz_response, dict):
        payload.update(supportwiz_response)
    elif isinstance(supportwiz_response, list):
        payload["data"] = supportwiz_response
    else:
        payload["data"] = supportwiz_response

    await emitter.info("🧱 Summaries:", payload=payload)
