# services/operational_service.py

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.etl.s3.services.org_normalize import (
    normalize_org,
    org_matches_filters,
    paginate,
)
from app.etl.s3.services.lookup_service import LookupService
from app.etl.s3.utils.s3_paths import (
    auditor_master_key,
    domain_lookup_key,
    project_json_key,
    projects_prefix,
    system_json_key,
)


class OperationalService:

    def __init__(self, s3):
        self.s3 = s3

    @staticmethod
    def org_profile_key(org_id: str) -> str:
        return f"organizations/{org_id}/org_profile.json"

    @staticmethod
    def ai_systems_store_key(org_id: str) -> str:
        return f"organizations/{org_id}/ai_systems.json"

    # 🔹 A. Get org_id from domain
    def get_org_by_domain(self, domain: str) -> Optional[str]:
        data = self.s3.read_json(domain_lookup_key(str(domain).strip().lower()))
        if not data:
            return None
        return data.get("org_id")

    # 🔹 B. Get all auditors
    def get_auditors(self) -> List[Dict]:
        data = self.s3.read_json(auditor_master_key())
        return data if data else []

    # 🔹 C. Assign org to auditor
    def assign_org(self, auditor_id: str, org_id: str) -> Dict:
        auditors = self.get_auditors()

        if not auditors:
            raise ValueError("Auditor master is empty")

        updated = False

        for auditor in auditors:
            if auditor.get("auditor_id") == auditor_id:

                if "organizations" not in auditor:
                    auditor["organizations"] = []

                if org_id not in auditor["organizations"]:
                    auditor["organizations"].append(org_id)

                updated = True
                break

        if not updated:
            raise ValueError(f"Auditor {auditor_id} not found")

        self.s3.write_json(auditor_master_key(), auditors)

        return {
            "status": "success",
            "auditor_id": auditor_id,
            "org_id": org_id,
        }

    def get_org_profile_raw(self, org_id: str) -> Optional[Dict]:
        return self.s3.read_json(self.org_profile_key(org_id))

    def merge_org_profile(self, org_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Shallow merge into org_profile.json; returns normalized ``Org``."""
        if not org_id:
            raise ValueError("org_id is required")

        key = self.org_profile_key(org_id)
        existing = self.s3.read_json(key) or {}
        merged = {**existing, **patch}
        merged["org_id"] = org_id

        if not merged.get("created_at"):
            merged["created_at"] = datetime.utcnow().isoformat()
        merged["updated_at"] = datetime.utcnow().isoformat()

        self.s3.write_json(key, merged)
        lk = LookupService(self.s3)
        lk.sync_organization_index_from_profile(merged)
        lk.sync_domains_from_profile(merged)
        return normalize_org(merged)

    def upsert_org_profile(
        self,
        org_id: str,
        name: str,
        email: str,
        status: str = "pending",
    ) -> Dict:
        return self.merge_org_profile(
            org_id,
            {"name": name, "email": email, "status": status},
        )

    def iter_org_ids(self) -> List[str]:
        prefix = "organizations/"
        seen: set[str] = set()
        out: List[str] = []
        continuation_token = None

        while True:
            params: Dict[str, Any] = {
                "Bucket": self.s3.bucket,
                "Prefix": prefix,
                "Delimiter": "/",
            }
            if continuation_token:
                params["ContinuationToken"] = continuation_token

            response = self.s3.client.list_objects_v2(**params)

            for cp in response.get("CommonPrefixes", []):
                org_prefix = cp.get("Prefix", "")
                parts = org_prefix.strip("/").split("/")
                if len(parts) >= 2:
                    oid = parts[1]
                    if oid and oid not in seen:
                        seen.add(oid)
                        out.append(oid)

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        out.sort()
        return out

    def get_all_organizations(self) -> List[Dict]:
        """List all orgs with normalized ``Org`` shape (full profile when present)."""
        results: List[Dict] = []
        for org_id in self.iter_org_ids():
            profile = self.get_org_profile_raw(org_id) or {
                "org_id": org_id,
                "name": org_id,
                "email": None,
                "status": "pending",
            }
            systems = self.list_ai_systems(org_id)
            profile["ai_system_wip_count"] = sum(
                1 for s in systems if (s.get("status") or "wip") != "completed"
            )
            profile["ai_system_completed_count"] = sum(
                1 for s in systems if s.get("status") == "completed"
            )
            results.append(normalize_org(profile))
        results.sort(key=lambda x: (x.get("name") or x.get("org_id") or ""))
        return results

    def list_organizations_filtered(
        self,
        *,
        onboarded_by: Optional[str] = None,
        onboarded_by_id: Optional[str] = None,
        org_type: Optional[str] = None,
        aict_approved: Optional[bool] = None,
        stage: Optional[str] = None,
        status: Optional[str] = None,
        archived: Optional[bool] = None,
        q: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[List[Dict], int]:
        all_rows = self.get_all_organizations()
        filtered = [
            o
            for o in all_rows
            if org_matches_filters(
                o,
                onboarded_by=onboarded_by,
                onboarded_by_id=onboarded_by_id,
                org_type=org_type,
                aict_approved=aict_approved,
                stage=stage,
                status=status,
                archived=archived,
                q=q,
            )
        ]
        page_rows, total = paginate(filtered, page, page_size)
        return page_rows, total

    def onboarding_decision(
        self,
        org_id: str,
        decision: str,
        email: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        decision = decision.lower().strip()
        patch: Dict[str, Any] = {}
        if decision == "approve":
            patch["status"] = "active"
            patch["aict_approved"] = True
        elif decision == "reject":
            patch["status"] = "rejected"
            patch["aict_approved"] = False
        else:
            raise ValueError("decision must be 'approve' or 'reject'")

        if email is not None:
            patch["onboarding_decision_email"] = email
        if reason is not None:
            patch["onboarding_reject_reason"] = reason

        existing = self.get_org_profile_raw(org_id)
        if not existing:
            raise ValueError(f"Unknown organization: {org_id}")

        return self.merge_org_profile(org_id, patch)

    def create_project(self, org_id: str, project_id: str, project_name: str) -> Dict[str, Any]:
        now = datetime.utcnow().isoformat()
        doc = {
            "project_id": project_id,
            "project_name": project_name,
            "created_at": now,
            "org_id": org_id,
        }
        self.s3.write_json(project_json_key(org_id, project_id), doc)
        return doc

    def get_project(self, org_id: str, project_id: str) -> Optional[Dict[str, Any]]:
        return self.s3.read_json(project_json_key(org_id, project_id))

    def list_project_ids(self, org_id: str) -> List[str]:
        prefix = projects_prefix(org_id)
        out: List[str] = []
        token = None
        while True:
            params: Dict[str, Any] = {
                "Bucket": self.s3.bucket,
                "Prefix": prefix,
                "Delimiter": "/",
            }
            if token:
                params["ContinuationToken"] = token
            resp = self.s3.client.list_objects_v2(**params)
            for cp in resp.get("CommonPrefixes", []):
                p = cp.get("Prefix", "").rstrip("/")
                parts = p.split("/")
                if len(parts) >= 4 and parts[-2] == "projects":
                    out.append(parts[-1])
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
        out.sort()
        return out

    def list_ai_systems(self, org_id: str) -> List[Dict[str, Any]]:
        raw = self.s3.read_json(self.ai_systems_store_key(org_id))
        if not raw:
            return []
        systems = raw.get("systems")
        return list(systems) if isinstance(systems, list) else []

    def add_ai_system(self, org_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        systems = self.list_ai_systems(org_id)
        system = {**body}
        system["org_id"] = org_id
        project_id = str(system.pop("project_id", None) or "default")
        if not system.get("system_id"):
            system["system_id"] = str(uuid.uuid4())
        sid = system["system_id"]
        if not system.get("added_at"):
            system["added_at"] = datetime.utcnow().isoformat()

        systems.append({**system, "project_id": project_id})
        self.s3.write_json(
            self.ai_systems_store_key(org_id),
            {
                "systems": systems,
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

        sys_doc = {
            "ai_system_id": sid,
            "name": system.get("name"),
            "description": system.get("description") or "",
            "version": system.get("version") or "v1",
            "created_at": system.get("added_at"),
            "org_id": org_id,
            "project_id": project_id,
        }
        self.s3.write_json(system_json_key(org_id, project_id, sid), sys_doc)
        LookupService(self.s3).write_ai_system_index(
            sid,
            org_id=org_id,
            project_id=project_id,
            audit_id=None,
            status=system.get("status"),
        )
        return {**system, "project_id": project_id}

    def filter_ai_systems(
        self,
        org_id: str,
        *,
        status: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = self.list_ai_systems(org_id)
        out = []
        for s in rows:
            if status and (s.get("status") or "") != status:
                continue
            if stage and (s.get("stage") or "") != stage:
                continue
            out.append(s)
        return out
