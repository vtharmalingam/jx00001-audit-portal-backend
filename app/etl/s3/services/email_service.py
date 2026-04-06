"""SMTP email delivery + S3-backed template management."""

from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from app.etl.s3.utils.helpers import utc_now
from app.etl.s3.utils.s3_paths import email_template_key, email_templates_prefix


DEFAULT_EMAIL_TEMPLATES: Dict[str, Dict[str, str]] = {
    "invite_user": {
        "subject": "You're invited to Audit Portal",
        "text": (
            "Hi {recipient_name},\n\n"
            "{inviter_name} invited you to Audit Portal as {role}.\n"
            "Set your password using this link:\n{invite_url}\n\n"
            "If you did not expect this invitation, please ignore this email.\n"
        ),
    },
    "resend_invite": {
        "subject": "Your Audit Portal invite link",
        "text": (
            "Hi {recipient_name},\n\n"
            "Here is your updated invite link:\n{invite_url}\n\n"
            "If you did not request this, please ignore this email.\n"
        ),
    },
    "onboard_firm_admin": {
        "subject": "Your firm account is ready",
        "text": (
            "Hi {recipient_name},\n\n"
            "Your firm \"{org_name}\" has been onboarded in Audit Portal.\n"
            "Set your password using this link:\n{invite_url}\n"
        ),
    },
    "onboard_individual_admin": {
        "subject": "Your organization account is ready",
        "text": (
            "Hi {recipient_name},\n\n"
            "Your organization \"{org_name}\" has been onboarded in Audit Portal.\n"
            "Set your password using this link:\n{invite_url}\n"
        ),
    },
    "onboard_firm_client_admin": {
        "subject": "Your client account is ready",
        "text": (
            "Hi {recipient_name},\n\n"
            "Your organization \"{org_name}\" has been onboarded under a partner firm.\n"
            "Set your password using this link:\n{invite_url}\n"
        ),
    },
}


def _normalize_scenario(raw: str) -> str:
    val = (raw or "").strip().lower()
    val = re.sub(r"[^a-z0-9_-]+", "_", val)
    return val.strip("_")


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


class EmailTemplateService:
    """Stores templates in S3 under platforms/email-templates/{scenario}.json."""

    def __init__(self, s3):
        self.s3 = s3

    def _read(self, scenario: str) -> Optional[Dict[str, Any]]:
        key = email_template_key(_normalize_scenario(scenario))
        return self.s3.read_json(key)

    def get_template(self, scenario: str) -> Optional[Dict[str, Any]]:
        scenario_key = _normalize_scenario(scenario)
        if not scenario_key:
            return None
        raw = self._read(scenario_key)
        if raw:
            raw.setdefault("scenario", scenario_key)
            return raw
        default = DEFAULT_EMAIL_TEMPLATES.get(scenario_key)
        if default:
            return {
                "scenario": scenario_key,
                "subject": default.get("subject", ""),
                "text": default.get("text", ""),
                "html": default.get("html", ""),
                "updated_at": None,
                "is_default": True,
            }
        return None

    def list_templates(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        paginator = self.s3.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.s3.bucket, Prefix=email_templates_prefix()):
            for obj in page.get("Contents", []):
                key = obj.get("Key", "")
                if not key.endswith(".json"):
                    continue
                data = self.s3.read_json(key) or {}
                scenario = (data.get("scenario") or key.rsplit("/", 1)[-1].replace(".json", "")).strip()
                if not scenario:
                    continue
                data["scenario"] = scenario
                data["is_default"] = False
                items.append(data)

        for scenario, default in DEFAULT_EMAIL_TEMPLATES.items():
            if any(i.get("scenario") == scenario for i in items):
                continue
            items.append(
                {
                    "scenario": scenario,
                    "subject": default.get("subject", ""),
                    "text": default.get("text", ""),
                    "html": default.get("html", ""),
                    "updated_at": None,
                    "is_default": True,
                }
            )
        return sorted(items, key=lambda x: x.get("scenario", ""))

    def upsert_template(self, scenario: str, subject: str, text: str, html: str = "") -> Dict[str, Any]:
        scenario_key = _normalize_scenario(scenario)
        if not scenario_key:
            raise ValueError("Scenario is required.")
        payload = {
            "scenario": scenario_key,
            "subject": (subject or "").strip(),
            "text": text or "",
            "html": html or "",
            "updated_at": utc_now(),
        }
        self.s3.write_json(email_template_key(scenario_key), payload)
        payload["is_default"] = False
        return payload

    def delete_template(self, scenario: str) -> bool:
        scenario_key = _normalize_scenario(scenario)
        if not scenario_key:
            return False
        existing = self._read(scenario_key)
        if not existing:
            return False
        self.s3.delete_object(email_template_key(scenario_key))
        return True

    def render(self, scenario: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        template = self.get_template(scenario)
        if not template:
            raise ValueError(f"Template scenario not found: {scenario}")
        vars_safe = SafeDict(**(variables or {}))
        return {
            "subject": (template.get("subject") or "").format_map(vars_safe),
            "text": (template.get("text") or "").format_map(vars_safe),
            "html": (template.get("html") or "").format_map(vars_safe),
        }


class EmailService:
    """SMTP sender using platform settings payload shape."""

    def __init__(self, smtp_settings: Dict[str, Any]):
        self.smtp = smtp_settings or {}

    @staticmethod
    def validate_smtp_settings(smtp: Dict[str, Any]) -> None:
        if not (smtp or {}).get("enabled"):
            raise ValueError("SMTP is disabled.")
        if not (smtp or {}).get("host"):
            raise ValueError("SMTP host is required.")
        port = int((smtp or {}).get("port") or 0)
        if port < 1 or port > 65535:
            raise ValueError("SMTP port must be between 1 and 65535.")
        if not (smtp or {}).get("fromAddress"):
            raise ValueError("From address is required.")

    def send_email(
        self,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str = "",
        reply_to: str = "",
    ) -> None:
        self.validate_smtp_settings(self.smtp)

        host = self.smtp.get("host")
        port = int(self.smtp.get("port") or 587)
        encryption = str(self.smtp.get("encryption") or "tls").lower()
        username = self.smtp.get("username") or ""
        password = self.smtp.get("password") or ""
        auth_required = bool(self.smtp.get("authRequired", True))
        verify_tls = bool(self.smtp.get("verifyTls", True))

        from_addr = self.smtp.get("fromAddress")
        from_name = self.smtp.get("fromName") or ""
        sender = f"{from_name} <{from_addr}>" if from_name else from_addr
        reply_to_addr = reply_to or self.smtp.get("replyTo") or ""

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email
        if reply_to_addr:
            msg["Reply-To"] = reply_to_addr
        msg.set_content(text_body or "")
        if html_body:
            msg.add_alternative(html_body, subtype="html")

        context = ssl.create_default_context()
        if not verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        if encryption == "ssl":
            server = smtplib.SMTP_SSL(host=host, port=port, context=context, timeout=20)
        else:
            server = smtplib.SMTP(host=host, port=port, timeout=20)

        with server:
            if encryption == "tls":
                server.starttls(context=context)
            if auth_required and username:
                server.login(username, password)
            server.send_message(msg)
