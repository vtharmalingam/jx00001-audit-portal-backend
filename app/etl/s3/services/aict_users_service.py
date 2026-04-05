"""
Purpose: AICT user directory in one S3 JSON document — list/create/update/delete users for
internal admin-style APIs.
"""

import uuid
from typing import Any, Dict, List, Optional

from app.etl.s3.utils.helpers import utc_now

from app.etl.s3.utils.s3_paths import aict_users_key


class AictUsersService:

    def __init__(self, s3):
        self.s3 = s3

    def _load(self) -> List[Dict]:
        # Step 1 — Read the single AICT users JSON from S3; missing/empty → [] from ``users``.
        data = self.s3.read_json(aict_users_key()) or {}
        return data.get("users", [])

    def _save(self, users: List[Dict]) -> None:
        # Step 1 — Replace the whole document ({users, updated_at}) so the roster stays one snapshot.
        self.s3.write_json(
            aict_users_key(),
            {"users": users, "updated_at": utc_now()},
        )

    def list_users(self) -> List[Dict]:
        # Step 1 — Return every user record currently stored (no filtering).
        return self._load()

    def create_user(self, name: str, email: str, role: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        # Step 1 — Load current roster from S3.
        users = self._load()
        now = utc_now()
        # Step 2 — Build a user row (caller may supply id; otherwise generate UUID).
        user = {
            "id": user_id or str(uuid.uuid4()),
            "name": name,
            "email": email,
            "role": role,
            "created_at": now,
            "updated_at": now,
        }
        # Step 3 — Append and persist the full list back to S3.
        users.append(user)
        self._save(users)
        # Step 4 — Return the new user for API responses.
        return user

    def update_user(self, user_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Step 1 — Load roster and find the matching id.
        users = self._load()
        for user in users:
            if user["id"] == user_id:
                # Step 2 — Apply only allowed fields when present and non-null.
                for key in ("name", "email", "role"):
                    if key in patch and patch[key] is not None:
                        user[key] = patch[key]
                user["updated_at"] = utc_now()
                # Step 3 — Save entire list; return updated row.
                self._save(users)
                return user
        # Step 4 — Unknown id → caller gets None.
        return None

    def delete_user(self, user_id: str) -> bool:
        # Step 1 — Load roster and drop the user with this id (if any).
        users = self._load()
        filtered = [u for u in users if u["id"] != user_id]
        # Step 2 — No row removed → signal failure without writing.
        if len(filtered) == len(users):
            return False
        # Step 3 — Persist shortened list.
        self._save(filtered)
        return True
