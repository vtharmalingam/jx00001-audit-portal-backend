import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.etl.s3.utils.s3_paths import aict_users_key


class AictUsersService:

    def __init__(self, s3):
        self.s3 = s3

    def _load(self) -> List[Dict]:
        data = self.s3.read_json(aict_users_key()) or {}
        return data.get("users", [])

    def _save(self, users: List[Dict]) -> None:
        self.s3.write_json(
            aict_users_key(),
            {"users": users, "updated_at": datetime.utcnow().isoformat()},
        )

    def list_users(self) -> List[Dict]:
        return self._load()

    def create_user(self, name: str, email: str, role: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        users = self._load()
        now = datetime.utcnow().isoformat()
        user = {
            "id": user_id or str(uuid.uuid4()),
            "name": name,
            "email": email,
            "role": role,
            "created_at": now,
            "updated_at": now,
        }
        users.append(user)
        self._save(users)
        return user

    def update_user(self, user_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        users = self._load()
        for user in users:
            if user["id"] == user_id:
                for key in ("name", "email", "role"):
                    if key in patch and patch[key] is not None:
                        user[key] = patch[key]
                user["updated_at"] = datetime.utcnow().isoformat()
                self._save(users)
                return user
        return None

    def delete_user(self, user_id: str) -> bool:
        users = self._load()
        filtered = [u for u in users if u["id"] != user_id]
        if len(filtered) == len(users):
            return False
        self._save(filtered)
        return True
