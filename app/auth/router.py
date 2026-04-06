"""Auth router — register, login, refresh, logout, me."""

import hashlib
import logging

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from typing import Dict, List, Optional, Tuple

from app.auth.dependencies import get_current_user, get_optional_user
from app.auth.permissions import list_permissions, require_permission
from app.auth.config import get_auth_config
from app.auth.schemas import (
    ActivateBody,
    AuthResponse,
    InviteBody,
    InviteResponse,
    LoginBody,
    OnboardFirmBody,
    OnboardFirmClientBody,
    OnboardIndividualBody,
    RegisterBody,
    UpdateRoleBody,
    UpdateUserBody,
    UserResponse,
)
from app.etl.s3.services.operational_service import OperationalService
from app.auth.service import AuthUserService
from app.auth.tokens import (
    clear_auth_cookies,
    create_access_token,
    create_invite_token,
    create_refresh_token,
    decode_token,
    set_auth_cookies,
)
from app.etl.s3.services.email_service import EmailService, EmailTemplateService
from app.etl.s3.services.platform_settings_service import PlatformSettingsService
from app.rest.deps import s3_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_auth_service() -> AuthUserService:
    return AuthUserService(s3_client)


def _derive_tier(role: str) -> str:
    """Derive tier from role string: 'firm_manager' → 'firm'."""
    parts = role.rsplit("_", 1)
    return parts[0] if len(parts) == 2 else role


def _is_admin(role: str) -> bool:
    return role.endswith("_admin")


def _same_tier(role_a: str, role_b: str) -> bool:
    return _derive_tier(role_a) == _derive_tier(role_b)


def _build_jwt_claims(user: Dict) -> Dict:
    """Build the claims dict embedded in every JWT."""
    return {
        "sub": user["id"],
        "email": user["email"],
        "role": user["role"],
        "tier": user.get("tier", _derive_tier(user["role"])),
        "org_id": user.get("org_id"),
    }


def _user_response(user: Dict, include_permissions: bool = True) -> UserResponse:
    return UserResponse(
        id=user["id"],
        name=user["name"],
        email=user["email"],
        role=user["role"],
        tier=user.get("tier", _derive_tier(user["role"])),
        status=user.get("status", "active"),
        org_id=user.get("org_id"),
        onboarded_by_id=user.get("onboarded_by_id"),
        aict_approved=user.get("aict_approved"),
        permissions=list_permissions(user["role"]) if include_permissions else None,
        created_at=user.get("created_at"),
    )


def _hash_token(token: str) -> str:
    """SHA-256 hash of a refresh token for safe storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def _send_scenario_email(
    scenario: str,
    to_email: str,
    variables: Dict[str, str],
) -> Tuple[bool, Optional[str]]:
    """Best-effort email sender for auth flows."""
    try:
        settings = PlatformSettingsService(s3_client).get_settings().get("settings", {})
        smtp = settings.get("smtp", {})
        rendered = EmailTemplateService(s3_client).render(scenario, variables)
        EmailService(smtp).send_email(
            to_email=to_email,
            subject=rendered.get("subject", ""),
            text_body=rendered.get("text", ""),
            html_body=rendered.get("html", ""),
        )
        return True, None
    except Exception as e:
        logger.warning("Email send skipped (%s): %s", scenario, e)
        return False, str(e)


# ── POST /auth/register ───────────────────────────────────────────────────

@router.post(
    "/register",
    summary="Register a new user",
    status_code=status.HTTP_201_CREATED,
    response_model=AuthResponse,
)
async def register(body: RegisterBody, response: Response):
    # Self-registration only allows admin roles (org onboarding)
    if not _is_admin(body.role):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ROLE_NOT_SELF_REGISTERABLE",
                "message": f"Role '{body.role}' cannot self-register. An admin must create this account.",
            },
        )

    svc = _get_auth_service()

    try:
        user = svc.create_user(
            name=body.name,
            email=body.email,
            password=body.password,
            role=body.role,
        )
    except ValueError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "REGISTER_FAILED", "message": str(e)},
        ) from e

    # Issue tokens
    claims = _build_jwt_claims(user)
    access = create_access_token(claims)
    refresh = create_refresh_token(claims)

    svc.store_refresh_token(user["id"], _hash_token(refresh))
    set_auth_cookies(response, access, refresh)

    return AuthResponse(user=_user_response(user), message="registered")


# ── POST /auth/invite ──────────────────────────────────────────────────────

@router.post(
    "/invite",
    summary="Admin invites a user — they set their own password via link",
    status_code=status.HTTP_201_CREATED,
    response_model=InviteResponse,
)
async def invite_user(
    body: InviteBody,
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    creator_role = current_user["role"] if current_user else "aict_admin"

    if _is_admin(body.role):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "CANNOT_CREATE_ADMIN", "message": "Cannot create another admin account"},
        )

    if current_user and not _same_tier(creator_role, body.role):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CROSS_TIER",
                "message": f"'{creator_role}' cannot create users in a different tier",
            },
        )

    svc = _get_auth_service()
    from ulid import ULID as _ULID
    user_id = str(_ULID()).upper()

    invite_token = create_invite_token({"sub": user_id, "email": body.email})

    # Invited user inherits the caller's org
    caller_org_id = current_user.get("org_id") if current_user else None

    try:
        user = svc.create_pending_user(
            name=body.name,
            email=body.email,
            role=body.role,
            invite_token_hash=_hash_token(invite_token),
            user_id=user_id,
            org_id=caller_org_id,
        )
    except ValueError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "INVITE_FAILED", "message": str(e)},
        ) from e

    cfg = get_auth_config()
    invite_url = f"{cfg.frontend_base_url}/auth/set-password?token={invite_token}"
    inviter_name = (current_user or {}).get("name", "Admin")
    email_sent, email_error = _send_scenario_email(
        scenario="invite_user",
        to_email=str(body.email),
        variables={
            "recipient_name": body.name,
            "inviter_name": inviter_name,
            "role": body.role,
            "invite_url": invite_url,
        },
    )

    return InviteResponse(
        user=_user_response(user),
        invite_url=invite_url,
        email_sent=email_sent,
        email_error=email_error,
    )


# ── POST /auth/activate ──────────────────────────────────────────────────

@router.post("/activate", summary="Activate account — user sets their password via invite token")
async def activate_account(body: ActivateBody):
    claims = decode_token(body.token)
    if not claims or claims.get("type") != "invite":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_INVITE_TOKEN", "message": "Invalid or expired invite link"},
        )

    user_id = claims.get("sub")
    svc = _get_auth_service()
    user = svc.find_by_id(user_id)

    if not user:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": "User not found"},
        )

    if user.get("status") != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "ALREADY_ACTIVATED", "message": "This account has already been activated"},
        )

    if user.get("invite_token_hash") != _hash_token(body.token):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_INVITE_TOKEN", "message": "Invalid invite token"},
        )

    activated = svc.activate_user(user_id, body.password)
    if not activated:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "ACTIVATION_FAILED", "message": "Failed to activate account"},
        )

    return {"message": "activated", "email": activated["email"]}


# ── POST /auth/resend-invite ──────────────────────────────────────────────

@router.post("/resend-invite", summary="Regenerate invite link for a pending user")
async def resend_invite(
    email: str = __import__("fastapi").Body(..., embed=True),
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    svc = _get_auth_service()
    cfg = get_auth_config()

    user = svc.find_by_email(email)
    if not user:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"No user found with email: {email}"},
        )

    if user.get("status") != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "ALREADY_ACTIVATED", "message": "This account is already activated."},
        )

    # Generate new invite token and store its hash
    invite_token = create_invite_token({"sub": user["id"], "email": email})
    svc.store_invite_token(user["id"], _hash_token(invite_token))

    invite_url = f"{cfg.frontend_base_url}/auth/set-password?token={invite_token}"
    email_sent, email_error = _send_scenario_email(
        scenario="resend_invite",
        to_email=email,
        variables={
            "recipient_name": user.get("name", "User"),
            "invite_url": invite_url,
        },
    )
    return {
        "invite_url": invite_url,
        "email": email,
        "email_sent": email_sent,
        "email_error": email_error,
    }


# ── POST /auth/onboard-firm ────────────────────────────────────────────────

@router.post(
    "/onboard-firm",
    summary="AICT Admin onboards a firm — creates org record + firm_admin user + invite",
    status_code=status.HTTP_201_CREATED,
)
async def onboard_firm(
    body: OnboardFirmBody,
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    from datetime import datetime

    svc = _get_auth_service()
    org_svc = OperationalService(s3_client)
    cfg = get_auth_config()

    # 1. Check if a firm org with this email already exists
    existing_orgs, _ = org_svc.list_organizations_filtered(
        org_type="firm", q=body.admin_email, page=1, page_size=1,
    )
    if existing_orgs:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "ONBOARD_FAILED", "message": f"A firm with this email already exists: {body.admin_email}"},
        )

    # 2. If an orphan user exists (from a deleted firm), remove it first
    existing_user = svc.find_by_email(body.admin_email)
    if existing_user:
        svc.delete_user(existing_user["id"])

    # 3. Create fresh firm_admin user with invite
    from ulid import ULID as _ULID
    user_id = str(_ULID()).upper()
    org_id = str(_ULID()).upper()
    invite_token = create_invite_token({"sub": user_id, "email": body.admin_email})

    try:
        user = svc.create_pending_user(
            name=body.admin_name or body.firm_name,
            email=body.admin_email,
            role="firm_admin",
            invite_token_hash=_hash_token(invite_token),
            user_id=user_id,
            org_id=org_id,
            onboarded_by_id=None,
            aict_approved=False,
        )
    except ValueError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "ONBOARD_FAILED", "message": str(e)},
        ) from e

    invite_url = f"{cfg.frontend_base_url}/auth/set-password?token={invite_token}"
    email_sent, email_error = _send_scenario_email(
        scenario="onboard_firm_admin",
        to_email=body.admin_email,
        variables={
            "recipient_name": body.admin_name or body.firm_name,
            "org_name": body.firm_name,
            "invite_url": invite_url,
        },
    )

    # 4. Create org record ONLY after user is created successfully
    org_svc.merge_org_profile(org_id, {
        "name": body.firm_name,
        "email": body.admin_email,
        "onboarded_by_type": "firm",
        "status": "pending_approval",
        "aict_approved": False,
        "stage": "not_started",
        "enrolled_at": datetime.utcnow().isoformat(),
    })

    return {
        "firm": {"org_id": org_id, "name": body.firm_name, "status": "pending_approval"},
        "user": _user_response(user),
        "invite_url": invite_url,
        "email_sent": email_sent,
        "email_error": email_error,
    }


# ── POST /auth/onboard-individual ──────────────────────────────────────────

@router.post(
    "/onboard-individual",
    summary="AICT Admin onboards an individual org — creates org + individual_admin user + invite",
    status_code=status.HTTP_201_CREATED,
)
async def onboard_individual(
    body: OnboardIndividualBody,
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    from datetime import datetime

    svc = _get_auth_service()
    org_svc = OperationalService(s3_client)
    cfg = get_auth_config()

    # 1. Check if an individual org with this email already exists
    existing_orgs, _ = org_svc.list_organizations_filtered(
        org_type="individual", q=body.admin_email, page=1, page_size=1,
    )
    if existing_orgs:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "ONBOARD_FAILED", "message": f"An organisation with this email already exists: {body.admin_email}"},
        )

    # 2. If an orphan user exists (from a deleted org), remove it first
    existing_user = svc.find_by_email(body.admin_email)
    if existing_user:
        svc.delete_user(existing_user["id"])

    # 3. Create fresh individual_admin user with invite
    from ulid import ULID as _ULID
    user_id = str(_ULID()).upper()
    org_id = str(_ULID()).upper()
    invite_token = create_invite_token({"sub": user_id, "email": body.admin_email})

    try:
        user = svc.create_pending_user(
            name=body.admin_name or body.org_name,
            email=body.admin_email,
            role="individual_admin",
            invite_token_hash=_hash_token(invite_token),
            user_id=user_id,
            org_id=org_id,
            onboarded_by_id=None,
            aict_approved=False,
        )
    except ValueError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "ONBOARD_FAILED", "message": str(e)},
        ) from e

    # 4. Create org record ONLY after user is created successfully
    org_svc.merge_org_profile(org_id, {
        "name": body.org_name,
        "email": body.admin_email,
        "onboarded_by_type": "individual",
        "status": "pending_approval",
        "aict_approved": False,
        "stage": "not_started",
        "enrolled_at": datetime.utcnow().isoformat(),
    })

    invite_url = f"{cfg.frontend_base_url}/auth/set-password?token={invite_token}"
    email_sent, email_error = _send_scenario_email(
        scenario="onboard_individual_admin",
        to_email=body.admin_email,
        variables={
            "recipient_name": body.admin_name or body.org_name,
            "org_name": body.org_name,
            "invite_url": invite_url,
        },
    )

    return {
        "org": {"org_id": org_id, "name": body.org_name, "status": "pending_approval"},
        "user": _user_response(user),
        "invite_url": invite_url,
        "email_sent": email_sent,
        "email_error": email_error,
    }


# ── POST /auth/onboard-firm-client ─────────────────────────────────────────

@router.post(
    "/onboard-firm-client",
    summary="Firm Admin onboards a client org under their firm",
    status_code=status.HTTP_201_CREATED,
)
async def onboard_firm_client(
    body: OnboardFirmClientBody,
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    from datetime import datetime

    svc = _get_auth_service()
    org_svc = OperationalService(s3_client)
    cfg = get_auth_config()

    # 1. Check if an org with this email already exists
    existing_orgs, _ = org_svc.list_organizations_filtered(
        q=body.admin_email, page=1, page_size=1,
    )
    if existing_orgs:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "ONBOARD_FAILED", 
                    "message": f"An organisation with this email already exists: {body.admin_email}"},
        )

    # 2. If an orphan user exists, remove it first
    existing_user = svc.find_by_email(body.admin_email)
    if existing_user:
        svc.delete_user(existing_user["id"])

    # 3. Create individual_admin user with invite
    from ulid import ULID as _ULID
    user_id = str(_ULID()).upper()
    invite_token = create_invite_token({"sub": user_id, "email": body.admin_email})

    # 4. Resolve the parent org ID (firm or individual)
    firm_id = body.firm_org_id
    if not firm_id and current_user:
        # Prefer org_id from JWT (set during login) — avoids S3 lookup
        firm_id = current_user.get("org_id")
    if not firm_id and current_user:
        # Fallback: look up the parent org by the logged-in admin's email
        caller_email = current_user.get("email", "")
        for _otype in ("firm", "individual"):
            parent_orgs, _ = org_svc.list_organizations_filtered(
                org_type=_otype, q=caller_email, page=1, page_size=1,
            )
            if parent_orgs:
                firm_id = parent_orgs[0].get("org_id")
                break

    org_id = str(_ULID()).upper()

    try:
        user = svc.create_pending_user(
            name=body.admin_name or body.org_name,
            email=body.admin_email,
            role="individual_admin",
            invite_token_hash=_hash_token(invite_token),
            user_id=user_id,
            org_id=org_id,
            onboarded_by_id=firm_id,
            aict_approved=False,
        )
    except ValueError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "ONBOARD_FAILED", "message": str(e)},
        ) from e

    # 5. Create org record linked to the parent

    org_svc.merge_org_profile(org_id, {
        "name": body.org_name,
        "email": body.admin_email,
        "onboarded_by_type": "firm_client",
        "onboarded_by_id": firm_id,
        "status": "pending_approval",
        "aict_approved": False,
        "stage": "not_started",
        "enrolled_at": datetime.utcnow().isoformat(),
    })

    invite_url = f"{cfg.frontend_base_url}/auth/set-password?token={invite_token}"
    email_sent, email_error = _send_scenario_email(
        scenario="onboard_firm_client_admin",
        to_email=body.admin_email,
        variables={
            "recipient_name": body.admin_name or body.org_name,
            "org_name": body.org_name,
            "invite_url": invite_url,
        },
    )

    return {
        "org": {"org_id": org_id, "name": body.org_name, "status": "pending_approval", "onboarded_by_id": firm_id},
        "user": _user_response(user),
        "invite_url": invite_url,
        "email_sent": email_sent,
        "email_error": email_error,
    }


# ── POST /auth/login ──────────────────────────────────────────────────────

@router.post("/login", summary="Authenticate and receive tokens via cookies", response_model=AuthResponse)
async def login(body: LoginBody, response: Response):
    svc = _get_auth_service()

    # Check for pending account before attempting auth
    raw_user = svc.find_by_email(body.email)
    if raw_user and raw_user.get("status") == "pending":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "ACCOUNT_PENDING", "message": "Please activate your account via the invite link sent to your email."},
        )

    user = svc.authenticate(body.email, body.password)

    if not user:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "BAD_CREDENTIALS", "message": "Invalid email or password"},
        )

    # Backfill org_id + aict_approved for legacy users (onboarded before ULID migration)
    tier = user.get("tier", _derive_tier(user["role"]))
    if tier in ("firm", "individual"):
        backfill = {}
        org_profile = None

        if not user.get("org_id"):
            from app.etl.s3.services.operational_service import OperationalService
            from app.rest.deps import s3_client as _s3
            org_svc = OperationalService(_s3)
            org_type = "firm" if tier == "firm" else "individual"
            matches, _ = org_svc.list_organizations_filtered(
                org_type=org_type, q=user.get("email", ""), page=1, page_size=1,
            )
            if matches:
                org_profile = matches[0]
                backfill["org_id"] = org_profile.get("org_id")
                user["org_id"] = backfill["org_id"]

        # Sync aict_approved from org profile if missing on user record
        if user.get("aict_approved") is None and org_profile:
            backfill["aict_approved"] = bool(org_profile.get("aict_approved"))
            user["aict_approved"] = backfill["aict_approved"]

        if backfill:
            svc.update_user(user["id"], backfill)

        # Block if still not approved
        if not user.get("aict_approved"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "AICT_APPROVAL_PENDING",
                    "message": "Your organisation is pending approval from AICT. You will be able to sign in once approved.",
                },
            )

    claims = _build_jwt_claims(user)
    access = create_access_token(claims)
    refresh = create_refresh_token(claims)

    svc.store_refresh_token(user["id"], _hash_token(refresh))
    set_auth_cookies(response, access, refresh)

    return AuthResponse(user=_user_response(user), message="logged_in")


# ── POST /auth/refresh ────────────────────────────────────────────────────

@router.post("/refresh", summary="Refresh access token using refresh cookie", response_model=AuthResponse)
async def refresh(response: Response, refresh_token: Optional[str] = Cookie(None)):
    if not refresh_token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "NO_REFRESH_TOKEN", "message": "Refresh token cookie missing"},
        )

    claims = decode_token(refresh_token)
    if not claims or claims.get("type") != "refresh":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_REFRESH", "message": "Invalid or expired refresh token"},
        )

    user_id = claims.get("sub")
    svc = _get_auth_service()

    # Validate the refresh token hash against stored value
    if not svc.validate_refresh_token(user_id, _hash_token(refresh_token)):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "REVOKED_TOKEN", "message": "Refresh token has been revoked"},
        )

    user = svc.find_by_id(user_id)
    if not user:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "USER_NOT_FOUND", "message": "User no longer exists"},
        )

    safe_user = AuthUserService._safe_user(user)

    # Rotate: issue new pair, store new refresh hash
    new_claims = _build_jwt_claims(safe_user)
    new_access = create_access_token(new_claims)
    new_refresh = create_refresh_token(new_claims)

    svc.store_refresh_token(user_id, _hash_token(new_refresh))
    set_auth_cookies(response, new_access, new_refresh)

    return AuthResponse(user=_user_response(safe_user), message="refreshed")


# ── POST /auth/logout ─────────────────────────────────────────────────────

@router.post("/logout", summary="Logout — clear cookies and revoke refresh token")
async def logout(
    response: Response,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_auth_service()
    svc.clear_refresh_token(current_user["id"])
    clear_auth_cookies(response)
    return {"message": "logged_out"}


# ── GET /auth/me ──────────────────────────────────────────────────────────

@router.get("/me", summary="Get current authenticated user", response_model=UserResponse)
async def me(current_user: Dict = Depends(get_current_user)):
    svc = _get_auth_service()
    user = svc.find_by_id(current_user["id"])

    if not user:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": "User no longer exists"},
        )

    return _user_response(AuthUserService._safe_user(user))


# ═══════════════════════════════════════════════════════════════════════════
# User & Role Management (admin-only)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/users", summary="List users — scoped to caller's tier", response_model=List[UserResponse])
async def list_users(
    tier: Optional[str] = None,
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    """
    Admins see their own tier by default.
    AICT admins can pass ?tier=firm to see other tiers.
    Unauthenticated (mock mode): returns all users if tier param given, else all.
    """
    svc = _get_auth_service()

    if not current_user:
        # No auth cookie — dev/mock mode, return by tier param or all
        users = svc.list_users(tier=tier)
        return [_user_response(u) for u in users]

    caller_tier = current_user.get("tier", _derive_tier(current_user["role"]))

    # AICT admins can view any tier
    if _is_admin(current_user["role"]) and caller_tier == "aict" and tier:
        effective_tier = tier
    else:
        effective_tier = caller_tier

    # Firm/individual callers only see users within their own organisation
    caller_org_id = None
    if caller_tier in ("firm", "individual"):
        caller_org_id = current_user.get("org_id")
        # Fallback: JWT may lack org_id for users onboarded before the ULID migration
        if not caller_org_id:
            full_user = svc.find_by_id(current_user["id"])
            caller_org_id = full_user.get("org_id") if full_user else None
        # Last resort: resolve org by email from the organizations index, then backfill
        if not caller_org_id:
            from app.etl.s3.services.operational_service import OperationalService
            from app.rest.deps import s3_client as _s3
            org_svc = OperationalService(_s3)
            org_type = "firm" if caller_tier == "firm" else "individual"
            matches, _ = org_svc.list_organizations_filtered(
                org_type=org_type, q=current_user.get("email", ""), page=1, page_size=1,
            )
            if matches:
                caller_org_id = matches[0].get("org_id")
                # Backfill so this lookup only happens once
                svc.update_user(current_user["id"], {"org_id": caller_org_id})

    users = svc.list_users(tier=effective_tier, org_id=caller_org_id)
    return [_user_response(u) for u in users]


@router.get("/users/{user_id}", summary="Get a single user", response_model=UserResponse)
async def get_user(
    user_id: str,
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    svc = _get_auth_service()
    user = svc.find_by_id(user_id)

    if not user:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "User not found"},
        )

    safe = AuthUserService._safe_user(user)

    # Tier isolation only when authenticated
    if current_user:
        caller_tier = current_user.get("tier", _derive_tier(current_user["role"]))
        user_tier = safe.get("tier", _derive_tier(safe["role"]))
        if caller_tier != "aict" and caller_tier != user_tier:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={"code": "CROSS_TIER", "message": "Cannot view users in another tier"},
            )

    return _user_response(safe)


@router.patch("/users/{user_id}", summary="Update user profile (name, email)", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UpdateUserBody,
    current_user: Optional[Dict] = Depends(get_optional_user),
):

    svc = _get_auth_service()
    target = svc.find_by_id(user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "User not found"})

    target_safe = AuthUserService._safe_user(target)

    # Tier isolation only when authenticated
    if current_user:
        if not _same_tier(current_user["role"], target_safe["role"]) and _derive_tier(current_user["role"]) != "aict":
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "CROSS_TIER", "message": "Cannot modify users in another tier"})

    patch = body.model_dump(exclude_none=True)

    # If role change is included, validate it
    if "role" in patch:
        new_role = patch["role"]
        if _is_admin(new_role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "CANNOT_ASSIGN_ADMIN", "message": "Cannot assign admin role"})
        if current_user and not _same_tier(current_user["role"], new_role) and _derive_tier(current_user["role"]) != "aict":
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "CROSS_TIER", "message": "Cannot assign roles in another tier"})

    updated = svc.update_user(user_id, patch)
    if not updated:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"code": "UPDATE_FAILED", "message": "Failed to update user"})

    return _user_response(updated)


@router.patch("/users/{user_id}/role", summary="Change user role (admin only)", response_model=UserResponse)
async def change_role(
    user_id: str,
    body: UpdateRoleBody,
    current_user: Optional[Dict] = Depends(get_optional_user),
):

    svc = _get_auth_service()
    target = svc.find_by_id(user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "User not found"})

    target_safe = AuthUserService._safe_user(target)

    # Cannot change another admin's role
    if _is_admin(target_safe["role"]):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "ADMIN_LOCKED", "message": "Admin role cannot be changed"},
        )

    # Cannot assign admin role
    if _is_admin(body.role):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "CANNOT_ASSIGN_ADMIN", "message": "Cannot assign admin role via this endpoint"},
        )

    # Must stay in same tier (unless caller is AICT admin)
    if current_user:
        caller_tier = _derive_tier(current_user["role"])
        if caller_tier != "aict" and not _same_tier(current_user["role"], body.role):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={"code": "CROSS_TIER", "message": "Cannot assign roles outside your tier"},
            )

    updated = svc.update_user(user_id, {"role": body.role})
    if not updated:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"code": "UPDATE_FAILED", "message": "Failed to update role"})

    return _user_response(updated)


@router.post("/users/{user_id}/reset-password", summary="Admin reset password for a user")
async def reset_password(
    user_id: str,
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    svc = _get_auth_service()
    target = svc.find_by_id(user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "User not found"})

    updated = svc.reset_password(user_id, "Admin@123")
    if not updated:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"code": "RESET_FAILED", "message": "Failed to reset password"})

    return {"message": "Password reset to default", "user": _user_response(updated)}


@router.delete("/users/{user_id}", summary="Delete a user (admin only)", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    current_user: Optional[Dict] = Depends(get_optional_user),
):

    if current_user and user_id == current_user["id"]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "SELF_DELETE", "message": "Cannot delete your own account"},
        )

    svc = _get_auth_service()
    target = svc.find_by_id(user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "User not found"})

    target_safe = AuthUserService._safe_user(target)

    if current_user:
        caller_tier = _derive_tier(current_user["role"])
        if caller_tier != "aict" and not _same_tier(current_user["role"], target_safe["role"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "CROSS_TIER", "message": "Cannot delete users in another tier"})

    if _is_admin(target_safe["role"]):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "ADMIN_LOCKED", "message": "Cannot delete an admin account"},
        )

    if not svc.delete_user(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "User not found"})
