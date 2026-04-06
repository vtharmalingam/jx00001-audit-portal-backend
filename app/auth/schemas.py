"""Pydantic request/response models for auth endpoints."""

from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


# ── Requests ───────────────────────────────────────────────────────────────

class RegisterBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    role: str = "individual_admin"


class InviteBody(BaseModel):
    """Admin invites a user — no password, user sets it via invite link."""
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    role: str


class OnboardFirmBody(BaseModel):
    """AICT Admin onboards a new firm — creates org + firm_admin user + invite."""
    firm_name: str = Field(..., min_length=1, max_length=200)
    admin_email: EmailStr
    admin_name: Optional[str] = None


class OnboardIndividualBody(BaseModel):
    """AICT Admin onboards an individual org — creates org + individual_admin user + invite."""
    org_name: str = Field(..., min_length=1, max_length=200)
    admin_email: EmailStr
    admin_name: Optional[str] = None


class OnboardFirmClientBody(BaseModel):
    """Firm Admin onboards a client org under their firm — creates org + individual_admin user + invite."""
    org_name: str = Field(..., min_length=1, max_length=200)
    admin_email: EmailStr
    admin_name: Optional[str] = None
    firm_org_id: Optional[str] = None


class ActivateBody(BaseModel):
    """User activates account via invite link — sets their own password."""
    token: str
    password: str = Field(..., min_length=8, max_length=128)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class RefreshBody(BaseModel):
    """Body is empty — refresh token comes from HttpOnly cookie."""
    pass


class UpdateRoleBody(BaseModel):
    role: str = Field(..., min_length=1)


class UpdateUserBody(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    role: Optional[str] = None


# ── Responses ──────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    tier: str
    status: Optional[str] = None
    org_id: Optional[str] = None
    onboarded_by_id: Optional[str] = None
    aict_approved: Optional[bool] = None
    permissions: Optional[List[str]] = None
    created_at: Optional[str] = None


class AuthResponse(BaseModel):
    """Returned on login/register/refresh — tokens are in cookies, not body."""
    user: UserResponse
    message: str = "ok"


class InviteResponse(BaseModel):
    """Returned on invite — includes the link for the admin to share."""
    user: UserResponse
    invite_url: str
    email_sent: bool = False
    email_error: Optional[str] = None
