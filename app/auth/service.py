"""Auth user service — S3-backed user storage with password hashing."""

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from ulid import ULID

from app.auth.passwords import hash_password, verify_password
from app.etl.s3.utils.s3_paths import _prefix

# Global lock to serialise read-modify-write on auth_users.json
_auth_users_lock = threading.Lock()

'''
-------------------------------------------------------------------------------------------------------------
- AuthUserService manages user accounts: id, name, email, password hash, assigned role (a string id like 
aict_admin or firm_practitioner), derived tier, status, invite/refresh token hashes, timestamps.

- Persisted in S3 as platform/auth_users.json.

- Handles register, login (authenticate), invite/activate, refresh token storage, user CRUD for auth.

So this file answers: “Which person has which role, and can they sign in?”
-------------------------------------------------------------------------------------------------------------
'''




def _auth_users_key() -> str:
    """S3 key for the auth users registry."""
    return _prefix("platform/auth_users.json")


class AuthUserService:
    """
    Manages authenticated users in S3.
    Separate from AictUsersService (platform/aict_users.json) to avoid
    mixing password hashes into the existing user management blob.
    """

    def __init__(self, s3):
        self.s3 = s3

    # ── Storage ────────────────────────────────────────────────────────────

    def _load(self) -> List[Dict]:
        data = self.s3.read_json(_auth_users_key()) or {}
        return data.get("users", [])

    def _save(self, users: List[Dict]) -> None:
        self.s3.write_json(
            _auth_users_key(),
            {"users": users, "updated_at": datetime.utcnow().isoformat()},
        )

    # ── Bootstrap ──────────────────────────────────────────────────────────

    # Stable org ULIDs for demo data (shared across users of the same org).
    _ORG_RISKFIRM = "01KNHFD14ARGVXCJTMN9282ABK"
    _ORG_HOOLI = "01KNHFD14CDRBQZTDY26479SAM"
    _ORG_GLOBEX = "01KNHFD14F1SMBM4BV672F14VD"
    _ORG_INITECH = "01KNHFD14JRTA62B98C0HDC5TH"

    _DEMO_USERS = [
        # AICT platform users — no org
        {"id": "01KNHFD13B8J8HPAEN3CFFK0J5", "email": "admin@aict.com",              "name": "AICT Admin",        "role": "aict_admin",              "org_id": None,         "onboarded_by_id": None, "aict_approved": True},
        {"id": "01KNHFD13KQVYPDAWCFA8X4YPP", "email": "manager@aict.com",            "name": "AICT Manager",      "role": "aict_manager",            "org_id": None,         "onboarded_by_id": None, "aict_approved": True},
        {"id": "01KNHFD13P76QSQEXQY64DXQDW", "email": "csap@aict.com",               "name": "AICT CSAP",         "role": "aict_csap",               "org_id": None,         "onboarded_by_id": None, "aict_approved": True},
        {"id": "01KNHFD13R02GD4RDM9A6SM6G9", "email": "practitioner@aict.com",        "name": "AICT Practitioner", "role": "aict_practitioner",       "org_id": None,         "onboarded_by_id": None, "aict_approved": True},
        # Firm users — all share the RiskFirm org
        {"id": "01KNHFD13VGA24DR79S775EXN0", "email": "firm.admin@riskfirm.com",      "name": "Firm Admin",        "role": "firm_admin",              "org_id": _ORG_RISKFIRM, "onboarded_by_id": None, "aict_approved": True},
        {"id": "01KNHFD13XK2VS4YQ7TM5910ZP", "email": "firm.manager@riskfirm.com",    "name": "Firm Manager",      "role": "firm_manager",            "org_id": _ORG_RISKFIRM, "onboarded_by_id": None, "aict_approved": True},
        {"id": "01KNHFD140KDJQQE6PDTMHMD2K", "email": "firm.practitioner@riskfirm.com","name": "Firm Practitioner", "role": "firm_practitioner",      "org_id": _ORG_RISKFIRM, "onboarded_by_id": None, "aict_approved": True},
        # Individual org admins — each has their own org
        {"id": "01KNHFD142GRJ1WTRGD8VJ7054", "email": "compliance@hooli.com",         "name": "Hooli Technologies","role": "individual_admin",        "org_id": _ORG_HOOLI,   "onboarded_by_id": None, "aict_approved": True},
        {"id": "01KNHFD1457YZHTFDM6DXX93BT", "email": "contact@globex.com",           "name": "Globex Industries", "role": "individual_manager",      "org_id": _ORG_GLOBEX,  "onboarded_by_id": None, "aict_approved": True},
        {"id": "01KNHFD147YVMN95RKTK7YATMX", "email": "info@initech.com",            "name": "Initech Solutions",  "role": "individual_practitioner", "org_id": _ORG_INITECH, "onboarded_by_id": None, "aict_approved": True},
    ]

    def ensure_demo_users(self, default_password: str = "Admin@123") -> int:
        """Seed any missing demo users. Returns count of users created."""
        created = 0
        for demo in self._DEMO_USERS:
            if not self.find_by_email(demo["email"]):
                self.create_user(
                    name=demo["name"],
                    email=demo["email"],
                    password=default_password,
                    role=demo["role"],
                    user_id=demo.get("id"),
                    status="active",
                    org_id=demo.get("org_id"),
                    onboarded_by_id=demo.get("onboarded_by_id"),
                    aict_approved=demo.get("aict_approved"),
                )
                created += 1
        return created

    # ── Queries ────────────────────────────────────────────────────────────

    def find_by_email(self, email: str) -> Optional[Dict]:
        email_lower = email.lower()
        for user in self._load():
            if user.get("email", "").lower() == email_lower:
                return user
        return None

    def find_by_id(self, user_id: str) -> Optional[Dict]:
        for user in self._load():
            if user["id"] == user_id:
                return user
        return None

    def list_users(self, tier: Optional[str] = None, org_id: Optional[str] = None) -> List[Dict]:
        users = self._load()
        if tier:
            users = [u for u in users if u.get("tier") == tier]
        if org_id:
            users = [u for u in users if u.get("org_id") == org_id]
        return [self._safe_user(u) for u in users]

    # ── Commands ───────────────────────────────────────────────────────────

    @staticmethod
    def _derive_tier(role: str) -> str:
        """Derive tier from role string: 'firm_manager' → 'firm'."""
        parts = role.rsplit("_", 1)
        return parts[0] if len(parts) == 2 else role

    def create_user(
        self,
        name: str,
        email: str,
        password: Optional[str] = None,
        role: str = "individual_admin",
        user_id: Optional[str] = None,
        status: str = "active",
        invite_token_hash: Optional[str] = None,
        org_id: Optional[str] = None,
        onboarded_by_id: Optional[str] = None,
        aict_approved: Optional[bool] = None,
    ) -> Dict[str, Any]:
        email_lower = email.lower()

        with _auth_users_lock:
            # Re-read inside the lock to prevent race conditions
            users = self._load()
            if any(u.get("email", "").lower() == email_lower for u in users):
                raise ValueError(f"Email already registered: {email}")

            now = datetime.utcnow().isoformat()
            user = {
                "id": user_id or str(ULID()).upper(),
                "name": name,
                "email": email_lower,
                "password_hash": hash_password(password) if password else None,
                "role": role,
                "tier": self._derive_tier(role),
                "status": status,
                "org_id": org_id,
                "onboarded_by_id": onboarded_by_id,
                "aict_approved": aict_approved,
                "invite_token_hash": invite_token_hash,
                "refresh_token_hash": None,
                "created_at": now,
                "updated_at": now,
            }
            users.append(user)
            self._save(users)
        return self._safe_user(user)

    def create_pending_user(
        self,
        name: str,
        email: str,
        role: str,
        invite_token_hash: str,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
        onboarded_by_id: Optional[str] = None,
        aict_approved: Optional[bool] = None,
    ) -> Dict[str, Any]:
        return self.create_user(
            name=name,
            email=email,
            password=None,
            role=role,
            user_id=user_id,
            status="pending",
            invite_token_hash=invite_token_hash,
            org_id=org_id,
            onboarded_by_id=onboarded_by_id,
            aict_approved=aict_approved,
        )

    def store_invite_token(self, user_id: str, invite_token_hash: str) -> None:
        """Update the invite token hash for a pending user (resend flow)."""
        users = self._load()
        for user in users:
            if user["id"] == user_id:
                user["invite_token_hash"] = invite_token_hash
                user["updated_at"] = datetime.utcnow().isoformat()
                break
        self._save(users)

    def activate_user(self, user_id: str, password: str) -> Optional[Dict]:
        """Set password and activate a pending user."""
        users = self._load()
        for user in users:
            if user["id"] == user_id:
                user["password_hash"] = hash_password(password)
                user["status"] = "active"
                user["invite_token_hash"] = None
                user["updated_at"] = datetime.utcnow().isoformat()
                self._save(users)
                return self._safe_user(user)
        return None

    def reset_password(self, user_id: str, new_password: str) -> Optional[Dict]:
        """Admin-only: reset a user's password and ensure they are active."""
        users = self._load()
        for user in users:
            if user["id"] == user_id:
                user["password_hash"] = hash_password(new_password)
                user["status"] = "active"
                user["updated_at"] = datetime.utcnow().isoformat()
                self._save(users)
                return self._safe_user(user)
        return None

    def update_user(self, user_id: str, patch: Dict[str, Any]) -> Optional[Dict]:
        """Update user fields (name, email, role). Recalculates tier on role change."""
        with _auth_users_lock:
            users = self._load()

            # If email is being changed, check for duplicates across all users
            new_email = patch.get("email")
            if new_email:
                new_email_lower = new_email.lower()
                for u in users:
                    if u["id"] != user_id and u.get("email", "").lower() == new_email_lower:
                        raise ValueError(f"Email already registered: {new_email}")

            for user in users:
                if user["id"] == user_id:
                    for key in ("name", "email", "role", "org_id", "onboarded_by_id", "aict_approved"):
                        if key in patch and patch[key] is not None:
                            user[key] = patch[key].lower() if key == "email" else patch[key]
                    if "role" in patch and patch["role"]:
                        user["tier"] = self._derive_tier(patch["role"])
                    user["updated_at"] = datetime.utcnow().isoformat()
                    self._save(users)
                    return self._safe_user(user)
        return None

    def delete_user(self, user_id: str) -> bool:
        with _auth_users_lock:
            users = self._load()
            filtered = [u for u in users if u["id"] != user_id]
            if len(filtered) == len(users):
                return False
            self._save(filtered)
        return True

    def authenticate(self, email: str, password: str) -> Optional[Dict]:
        """Verify credentials. Returns user dict (without password_hash) or None."""
        user = self.find_by_email(email)
        if not user:
            return None
        if user.get("status") == "pending":
            return None
        if not user.get("password_hash"):
            return None
        if not verify_password(password, user["password_hash"]):
            return None
        return self._safe_user(user)

    # ── Refresh token management ───────────────────────────────────────────

    def store_refresh_token(self, user_id: str, refresh_token_hash: str) -> None:
        users = self._load()
        for user in users:
            if user["id"] == user_id:
                user["refresh_token_hash"] = refresh_token_hash
                user["updated_at"] = datetime.utcnow().isoformat()
                break
        self._save(users)

    def validate_refresh_token(self, user_id: str, refresh_token_hash: str) -> bool:
        user = self.find_by_id(user_id)
        if not user:
            return False
        return user.get("refresh_token_hash") == refresh_token_hash

    def clear_refresh_token(self, user_id: str) -> None:
        self.store_refresh_token(user_id, None)

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _safe_user(user: Dict) -> Dict:
        """Return user dict without sensitive fields."""
        return {k: v for k, v in user.items() if k not in ("password_hash", "refresh_token_hash", "invite_token_hash")}
