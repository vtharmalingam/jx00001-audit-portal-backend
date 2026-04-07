from typing import Any, Dict

from app.etl.s3.utils.helpers import utc_now
from app.etl.s3.utils.s3_paths import platform_settings_key


DEFAULT_PLATFORM_SETTINGS: Dict[str, Any] = {
    "general": {
        "platformName": "",
        "tagline": "",
        "supportEmail": "",
        "logoUrl": "",
        "faviconUrl": "",
        "defaultAssessmentDeadlineDays": 30,
        "maxFileUploadMB": 5,
        "defaultTimezone": "UTC",
        "maintenanceMode": False,
        "sessionTimeoutMinutes": 60,
    },
    "smtp": {
        "enabled": True,
        "host": "mailpit",
        "port": 1025,
        "encryption": "none",
        "username": "",
        "password": "",
        "fromAddress": "noreply@aict.com",
        "fromName": "AICT Platform",
        "replyTo": "",
        "authRequired": False,
        "verifyTls": False,
    },
}


class PlatformSettingsService:
    def __init__(self, s3):
        self.s3 = s3

    def _merge(self, incoming: Dict[str, Any] | None) -> Dict[str, Any]:
        incoming = incoming or {}
        return {
            "general": {
                **DEFAULT_PLATFORM_SETTINGS["general"],
                **(incoming.get("general") or {}),
            },
            "smtp": {
                **DEFAULT_PLATFORM_SETTINGS["smtp"],
                **(incoming.get("smtp") or {}),
            },
        }

    def get_settings(self) -> Dict[str, Any]:
        raw = self.s3.read_json(platform_settings_key()) or {}
        merged = self._merge(raw.get("settings") if "settings" in raw else raw)
        return {"settings": merged, "updated_at": raw.get("updated_at")}

    def save_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        merged = self._merge(settings)
        payload = {"settings": merged, "updated_at": utc_now()}
        self.s3.write_json(platform_settings_key(), payload)
        return payload

    def validate_smtp_payload_for_test(self, smtp: Dict[str, Any]) -> None:
        merged = {**DEFAULT_PLATFORM_SETTINGS["smtp"], **(smtp or {})}
        if not merged.get("enabled"):
            raise ValueError("SMTP is disabled.")
        if not merged.get("host"):
            raise ValueError("SMTP host is required.")
        port = int(merged.get("port") or 0)
        if port < 1 or port > 65535:
            raise ValueError("SMTP port must be between 1 and 65535.")
        if not merged.get("fromAddress"):
            raise ValueError("From address is required.")
