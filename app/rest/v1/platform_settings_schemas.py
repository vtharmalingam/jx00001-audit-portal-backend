from typing import Optional

from pydantic import BaseModel, Field


class PlatformGeneralSettings(BaseModel):
    platformName: Optional[str] = ""
    tagline: Optional[str] = ""
    supportEmail: Optional[str] = ""
    logoUrl: Optional[str] = ""
    faviconUrl: Optional[str] = ""
    defaultAssessmentDeadlineDays: Optional[int] = Field(default=30, ge=1, le=365)
    maxFileUploadMB: Optional[int] = Field(default=5, ge=1, le=200)
    defaultTimezone: Optional[str] = "UTC"
    maintenanceMode: Optional[bool] = False
    sessionTimeoutMinutes: Optional[int] = Field(default=60, ge=5, le=1440)


class PlatformSmtpSettings(BaseModel):
    enabled: Optional[bool] = False
    host: Optional[str] = ""
    port: Optional[int] = Field(default=587, ge=1, le=65535)
    encryption: Optional[str] = "tls"
    username: Optional[str] = ""
    password: Optional[str] = ""
    fromAddress: Optional[str] = ""
    fromName: Optional[str] = ""
    replyTo: Optional[str] = ""
    authRequired: Optional[bool] = True
    verifyTls: Optional[bool] = True


class PlatformSettingsBody(BaseModel):
    general: PlatformGeneralSettings
    smtp: PlatformSmtpSettings


class SmtpTestBody(BaseModel):
    smtp: PlatformSmtpSettings
