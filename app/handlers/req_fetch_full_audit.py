from app.engine.emitter import EventEmitter
from app.engine.message_router import route
from app.etl.s3.services.report_service import ReportService
from app.handlers.common import s3_client


@route("AI-ASSESSMENT-REQ", "FETCH-GAP-ANALYSIS")
@route("AI-ASSESSMENT-REQ", "FETCH-FULL-AUDIT")
async def fetch_full_audit(ws, client_id, request, manager):
    emitter = EventEmitter(websocket=ws)

    reqData = request.reqData

    if not reqData:
        await emitter.error("🚩 Missing 'reqData'")
        return

    org_id = reqData.get("org_id")
    audit_id = reqData.get("audit_id", "0")

    if not org_id:
        await emitter.error("🚩 Missing org_id")
        return

    try:
        report_service = ReportService(s3_client)

        result = report_service.get_full_audit_view(org_id, audit_id)

        await emitter.info(
            "📊 Full Audit View",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "status": True,
                **result,
            },
        )

    except Exception as e:
        await emitter.error(
            f"❌ Failed: {str(e)}",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
            },
        )
