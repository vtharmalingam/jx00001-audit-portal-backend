from app.engine.emitter import EventEmitter
from app.engine.message_router import route
from app.etl.s3.services.operational_service import OperationalService
from app.handlers.common import s3_client


@route("AI-ASSESSMENT-REQ", "FETCH-ORGANIZATIONS")
async def fetch_organizations(ws, client_id, request, manager):
    emitter = EventEmitter(websocket=ws)

    try:
        service = OperationalService(s3_client)

        orgs = service.get_all_organizations()

        await emitter.info(
            "🏢 Fetch Organizations",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "status": True,
                "total": len(orgs),
                "organizations": orgs,
            },
        )

    except Exception as e:
        await emitter.error(
            f"❌ Failed to fetch organizations: {str(e)}",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
            },
        )
