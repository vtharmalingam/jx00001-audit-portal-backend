"""Auth user service — S3-backed user storage with password hashing."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.auth.passwords import hash_password, verify_password
from app.etl.s3.utils.s3_paths import _prefix


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

    def list_users(self, tier: Optional[str] = None) -> List[Dict]:
        users = self._load()
        if tier:
            users = [u for u in users if u.get("tier") == tier]
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
    ) -> Dict[str, Any]:
        if self.find_by_email(email):
            raise ValueError(f"Email already registered: {email}")

        users = self._load()
        now = datetime.utcnow().isoformat()
        user = {
            "id": user_id or str(uuid.uuid4()),
            "name": name,
            "email": email.lower(),
            "password_hash": hash_password(password) if password else None,
            "role": role,
            "tier": self._derive_tier(role),
            "status": status,
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
    ) -> Dict[str, Any]:
        return self.create_user(
            name=name,
            email=email,
            password=None,
            role=role,
            user_id=user_id,
            status="pending",
            invite_token_hash=invite_token_hash,
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

    def update_user(self, user_id: str, patch: Dict[str, Any]) -> Optional[Dict]:
        """Update user fields (name, email, role). Recalculates tier on role change."""
        users = self._load()
        for user in users:
            if user["id"] == user_id:
                for key in ("name", "email", "role"):
                    if key in patch and patch[key] is not None:
                        user[key] = patch[key]
                if "role" in patch and patch["role"]:
                    user["tier"] = self._derive_tier(patch["role"])
                user["updated_at"] = datetime.utcnow().isoformat()
                self._save(users)
                return self._safe_user(user)
        return None

    def delete_user(self, user_id: str) -> bool:
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
