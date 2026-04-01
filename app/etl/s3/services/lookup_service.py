# services/lookup_service.py

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from app.etl.s3.utils.s3_paths import (
    ai_system_lookup_key,
    domain_lookup_key,
    org_lookup_key,
)


class LookupService:
    def __init__(self, s3):
        self.s3 = s3

    def write_domain_map(self, domain: str, org_id: str) -> None:
        d = str(domain).strip().lower()
        if not d or not org_id:
            return
        self.s3.write_json(domain_lookup_key(d), {"org_id": org_id})

    def sync_domains_from_profile(self, profile: Dict[str, Any]) -> None:
        org_id = profile.get("org_id")
        domains = profile.get("domains")
        if not org_id or not isinstance(domains, list):
            return
        for d in domains:
            if d:
                self.write_domain_map(str(d), str(org_id))

    def write_organization_index(self, org_id: str, summary: Dict[str, Any]) -> None:
        payload = {
            **summary,
            "org_id": org_id,
            "indexed_at": datetime.utcnow().isoformat(),
        }
        self.s3.write_json(org_lookup_key(org_id), payload)

    def sync_organization_index_from_profile(self, profile: Dict[str, Any]) -> None:
        org_id = profile.get("org_id")
        if not org_id:
            return
        summary = {
            "name": profile.get("name"),
            "status": profile.get("status"),
            "org_type": profile.get("org_type")
            or profile.get("onboarded_by_type")
            or profile.get("org_channel"),
            "updated_at": profile.get("updated_at"),
        }
        self.write_organization_index(str(org_id), summary)

    def write_ai_system_index(
        self,
        ai_system_id: str,
        *,
        org_id: str,
        project_id: str,
        audit_id: Optional[str] = None,
        status: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        data: Dict[str, Any] = {
            "ai_system_id": ai_system_id,
            "org_id": org_id,
            "project_id": project_id,
            "audit_id": audit_id,
            "status": status,
            "updated_at": datetime.utcnow().isoformat(),
        }
        if extra:
            data.update(extra)
        self.s3.write_json(ai_system_lookup_key(ai_system_id), data)

    def get_ai_system_index(self, ai_system_id: str) -> Optional[Dict[str, Any]]:
        return self.s3.read_json(ai_system_lookup_key(ai_system_id))

    def patch_ai_system_audit(
        self,
        ai_system_id: str,
        audit_id: str,
        status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        cur = self.get_ai_system_index(ai_system_id)
        if not cur:
            return None
        cur["audit_id"] = audit_id
        if status is not None:
            cur["status"] = status
        cur["updated_at"] = datetime.utcnow().isoformat()
        self.s3.write_json(ai_system_lookup_key(ai_system_id), cur)
        return cur
