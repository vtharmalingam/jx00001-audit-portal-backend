from typing import Dict

from fastapi import APIRouter, HTTPException, status

from app.etl.s3.services.email_service import EmailService, EmailTemplateService
from app.etl.s3.services.platform_settings_service import PlatformSettingsService
from app.rest.deps import s3_client
from app.rest.v1.platform_settings_schemas import (
    EmailTemplateBody,
    PlatformSettingsBody,
    SendEmailBody,
    SmtpTestBody,
)

router = APIRouter(prefix="/platform-settings", tags=["platform-settings"])


def _svc() -> PlatformSettingsService:
    return PlatformSettingsService(s3_client)


def _template_svc() -> EmailTemplateService:
    return EmailTemplateService(s3_client)


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


@router.post("/smtp/send-test", summary="Send a real SMTP test email")
async def smtp_send_test(body: SendEmailBody):
    settings = _svc().get_settings().get("settings", {})
    smtp = settings.get("smtp", {})
    try:
        EmailService(smtp).send_email(
            to_email=body.to,
            subject=body.subject or "SMTP test email from Audit Portal",
            text_body=body.text or "SMTP test email sent successfully.",
            html_body=body.html or "",
            reply_to=body.reply_to or "",
        )
    except ValueError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "SMTP_CONFIG_INVALID", "message": str(e)},
        ) from e
    except Exception as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={"code": "SMTP_SEND_FAILED", "message": str(e)},
        ) from e
    return {"ok": True, "message": "Test email sent."}


@router.get("/email-templates", summary="List email templates")
async def list_email_templates():
    return {"templates": _template_svc().list_templates()}


@router.get("/email-templates/{scenario}", summary="Get email template by scenario")
async def get_email_template(scenario: str):
    template = _template_svc().get_template(scenario)
    if not template:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "TEMPLATE_NOT_FOUND", "message": f"Unknown scenario: {scenario}"},
        )
    return {"template": template}


@router.put("/email-templates/{scenario}", summary="Create or update email template")
async def put_email_template(scenario: str, body: EmailTemplateBody):
    if body.scenario.strip().lower() != scenario.strip().lower():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "SCENARIO_MISMATCH", "message": "Body scenario must match path scenario."},
        )
    try:
        saved = _template_svc().upsert_template(
            scenario=scenario,
            subject=body.subject,
            text=body.text,
            html=body.html,
        )
    except ValueError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "TEMPLATE_INVALID", "message": str(e)},
        ) from e
    return {"template": saved}


@router.delete("/email-templates/{scenario}", summary="Delete custom template and fall back to default")
async def delete_email_template(scenario: str):
    deleted = _template_svc().delete_template(scenario)
    if not deleted:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "TEMPLATE_NOT_FOUND", "message": f"No custom template found: {scenario}"},
        )
    return {"ok": True, "message": "Template deleted. Default (if any) will be used."}


@router.post("/email/send", summary="Send email by scenario template or explicit body")
async def send_email(body: SendEmailBody):
    settings = _svc().get_settings().get("settings", {})
    smtp = settings.get("smtp", {})
    template_svc = _template_svc()

    try:
        rendered: Dict[str, str] = {"subject": body.subject or "", "text": body.text or "", "html": body.html or ""}
        if body.scenario:
            rendered = template_svc.render(body.scenario, body.template_vars)
            # Allow explicit body fields to override rendered output.
            if body.subject is not None:
                rendered["subject"] = body.subject
            if body.text is not None:
                rendered["text"] = body.text
            if body.html is not None:
                rendered["html"] = body.html

        if not rendered.get("subject"):
            raise ValueError("Email subject is required.")
        if not rendered.get("text") and not rendered.get("html"):
            raise ValueError("Either text or html content is required.")

        EmailService(smtp).send_email(
            to_email=body.to,
            subject=rendered["subject"],
            text_body=rendered.get("text", ""),
            html_body=rendered.get("html", ""),
            reply_to=body.reply_to or "",
        )
    except ValueError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "EMAIL_INVALID", "message": str(e)},
        ) from e
    except Exception as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={"code": "EMAIL_SEND_FAILED", "message": str(e)},
        ) from e

    return {"ok": True, "message": "Email sent."}
