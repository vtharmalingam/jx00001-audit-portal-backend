from fastapi import APIRouter, HTTPException, status

from app.etl.s3.services.platform_settings_service import PlatformSettingsService
from app.rest.deps import s3_client
from app.rest.v1.platform_settings_schemas import PlatformSettingsBody, SmtpTestBody

router = APIRouter(prefix="/platform-settings", tags=["platform-settings"])


def _svc() -> PlatformSettingsService:
    return PlatformSettingsService(s3_client)


@router.get("", summary="Get platform settings")
async def get_platform_settings():
    return _svc().get_settings()


@router.patch("", summary="Update platform settings")
async def patch_platform_settings(body: PlatformSettingsBody):
    payload = body.model_dump()
    saved = _svc().save_settings(payload)
    return saved


@router.post("/smtp/test", summary="Validate SMTP configuration test request")
async def smtp_test(body: SmtpTestBody):
    smtp_payload = body.smtp.model_dump()
    try:
        _svc().validate_smtp_payload_for_test(smtp_payload)
    except ValueError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "SMTP_TEST_INVALID", "message": str(e)},
        ) from e

    return {
        "ok": True,
        "message": "SMTP test request accepted.",
        "smtp": {
            "host": smtp_payload.get("host", ""),
            "port": smtp_payload.get("port", 587),
            "encryption": smtp_payload.get("encryption", "tls"),
            "fromAddress": smtp_payload.get("fromAddress", ""),
        },
    }
