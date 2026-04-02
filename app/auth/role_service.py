"""Role definitions service — S3-backed CRUD for the platform role catalog."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.etl.s3.utils.s3_paths import _prefix


def _roles_key() -> str:
    return _prefix("platform/roles.json")


# ── Default seed roles (used on first load when S3 is empty) ───────────────

_DEFAULT_ROLES = [
    {
        "id": "aict_admin",
        "display_name": "AICT Admin",
        "tier": "aict",
        "level": "admin",
        "description": "Platform owner — full access including settings, library management, and user administration.",
        "permissions": [
            "users.manage", "org.manage", "settings.manage", "library.manage",
            "library.read", "assessment.fill", "reports.view", "reports.export",
            "onboard.create", "archived.view", "dashboard.view",
        ],
    },
    {
        "id": "aict_manager",
        "display_name": "AICT Manager",
        "tier": "aict",
        "level": "manager",
        "description": "Oversees assessments, reviews reports, and monitors organisation progress.",
        "permissions": [
            "assessment.review", "reports.view", "reports.export", "reports.annotate",
            "onboard.create", "archived.view", "dashboard.view", "library.read",
        ],
    },
    {
        "id": "aict_practitioner",
        "display_name": "AICT Practitioner",
        "tier": "aict",
        "level": "practitioner",
        "description": "Fills assessments for assigned AI systems and clients.",
        "permissions": [
            "assessment.fill", "dashboard.view", "library.read", "desk.assigned",
        ],
    },
    {
        "id": "firm_admin",
        "display_name": "Firm Admin",
        "tier": "firm",
        "level": "admin",
        "description": "Firm owner — manages firm users, organisations, and onboarding.",
        "permissions": [
            "users.manage", "org.manage", "onboard.create", "reports.view",
            "reports.export", "archived.view", "dashboard.view", "library.read",
        ],
    },
    {
        "id": "firm_manager",
        "display_name": "Firm Manager",
        "tier": "firm",
        "level": "manager",
        "description": "Reviews assessments, manages client relationships, and performs audits.",
        "permissions": [
            "assessment.review", "reports.view", "reports.export", "reports.annotate",
            "onboard.create", "archived.view", "dashboard.view", "library.read",
        ],
    },
    {
        "id": "firm_practitioner",
        "display_name": "Firm Practitioner",
        "tier": "firm",
        "level": "practitioner",
        "description": "Fills assessment declarations for assigned organisations.",
        "permissions": [
            "assessment.fill", "dashboard.view", "library.read", "desk.assigned",
        ],
    },
    {
        "id": "individual_admin",
        "display_name": "Individual Admin",
        "tier": "individual",
        "level": "admin",
        "description": "Organisation owner — manages team and audit setup.",
        "permissions": [
            "users.manage", "org.manage", "onboard.create", "reports.view",
            "reports.export", "archived.view", "dashboard.view", "library.read",
        ],
    },
    {
        "id": "individual_manager",
        "display_name": "Individual Manager",
        "tier": "individual",
        "level": "manager",
        "description": "Manages assessments and reviews gap analysis reports.",
        "permissions": [
            "assessment.review", "reports.view", "reports.export", "reports.annotate",
            "onboard.create", "archived.view", "dashboard.view", "library.read",
        ],
    },
    {
        "id": "individual_practitioner",
        "display_name": "Individual Practitioner",
        "tier": "individual",
        "level": "practitioner",
        "description": "Fills assessment declarations for own organisation.",
        "permissions": [
            "assessment.fill", "dashboard.view", "library.read", "desk.assigned",
        ],
    },
]


class RoleService:
    """CRUD for the platform role catalog stored in S3."""

    def __init__(self, s3):
        self.s3 = s3

    def _load(self) -> List[Dict]:
        data = self.s3.read_json(_roles_key())
        if not data or not data.get("roles"):
            # First run — seed defaults
            self._save(_DEFAULT_ROLES)
            return list(_DEFAULT_ROLES)
        return data["roles"]

    def _save(self, roles: List[Dict]) -> None:
        self.s3.write_json(
            _roles_key(),
            {"roles": roles, "updated_at": datetime.utcnow().isoformat()},
        )

    def list_roles(self, tier: Optional[str] = None) -> List[Dict]:
        roles = self._load()
        if tier:
            roles = [r for r in roles if r.get("tier") == tier]
        return roles

    def get_role(self, role_id: str) -> Optional[Dict]:
        for role in self._load():
            if role["id"] == role_id:
                return role
        return None

    def create_role(self, role_data: Dict[str, Any]) -> Dict:
        roles = self._load()
        if any(r["id"] == role_data["id"] for r in roles):
            raise ValueError(f"Role '{role_data['id']}' already exists")

        now = datetime.utcnow().isoformat()
        role = {
            "id": role_data["id"],
            "display_name": role_data["display_name"],
            "tier": role_data.get("tier", ""),
            "level": role_data.get("level", ""),
            "description": role_data.get("description", ""),
            "permissions": role_data.get("permissions", []),
            "created_at": now,
            "updated_at": now,
        }
        roles.append(role)
        self._save(roles)
        return role

    def update_role(self, role_id: str, patch: Dict[str, Any]) -> Optional[Dict]:
        roles = self._load()
        for role in roles:
            if role["id"] == role_id:
                for key in ("display_name", "description", "permissions", "tier", "level"):
                    if key in patch:
                        role[key] = patch[key]
                role["updated_at"] = datetime.utcnow().isoformat()
                self._save(roles)
                return role
        return None

    def delete_role(self, role_id: str) -> bool:
        roles = self._load()
        filtered = [r for r in roles if r["id"] != role_id]
        if len(filtered) == len(roles):
            return False
        self._save(filtered)
        return True

    def get_permissions_for_role(self, role_id: str) -> List[str]:
        """Used by the permission system to resolve permissions dynamically."""
        role = self.get_role(role_id)
        if role:
            return role.get("permissions", [])
        return []
