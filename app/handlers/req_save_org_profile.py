from app.engine.emitter import EventEmitter
from app.engine.message_router import route
from app.etl.s3.services.operational_service import OperationalService
from app.handlers.common import s3_client


@route("AI-ASSESSMENT-REQ", "SAVE-ORG-PROFILE")
async def save_org_profile(ws, client_id, request, manager):
    emitter = EventEmitter(websocket=ws)

    reqData = request.reqData

    if not reqData:
        await emitter.error("🚩 Missing 'reqData'")
        return

    org_id = reqData.get("org_id")
    name = reqData.get("name")
    email = reqData.get("email")
    status = reqData.get("status", "pending")

    if not all([org_id, name, email]):
        await emitter.error("🚩 Required: org_id, name, email")
        return

    try:
        service = OperationalService(s3_client)

        result = service.upsert_org_profile(
            org_id=org_id,
            name=name,
            email=email,
            status=status,
        )

        await emitter.info(
            "🏢 Save Org Profile",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "status": True,
                "org_id": org_id,
                "data": result,
            },
        )

    except Exception as e:
        await emitter.error(
            f"❌ Failed to save org profile: {str(e)}",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
            },
        )
