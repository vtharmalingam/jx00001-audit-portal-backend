"""
Purpose: Organization operations — org_profile.json, list/filter orgs, projects, ai_systems.json
registry, domain→org lookup, auditor master assignment, denormalized AI-system counts on
profiles, org index maintenance.
"""

from typing import Any, Dict, List, Optional

from app.etl.s3.utils.helpers import utc_now

from app.etl.s3.services.org_normalize import (
    normalize_org,
    org_matches_filters,
    paginate,
)
from app.etl.s3.services.audit_lifecycle_service import AuditLifecycleService
from app.etl.s3.services.lookup_service import LookupService
from app.etl.s3.utils.ids import new_audit_ulid
from app.etl.s3.utils.s3_paths import (
    auditor_master_key,
    domain_lookup_key,
    org_profile_key,
    project_json_key,
    projects_prefix,
    system_json_key,
    systems_prefix,
)

ORG_INDEX_KEY = "indexes/organizations_index.json"


class OperationalService:

    def __init__(self, s3):
        self.s3 = s3

    # ── Org Profile ──────────────────────────────────────────────────────────

    def get_org_profile_raw(self, org_id: str) -> Optional[Dict]:
        return self.s3.read_json(org_profile_key(org_id))

    def merge_org_profile(self, org_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Shallow merge into org_profile.json; returns normalized ``Org``."""
        if not org_id:
            raise ValueError("org_id is required")

        key = org_profile_key(org_id)
        existing = self.s3.read_json(key) or {}
        merged = {**existing, **patch}
        merged["org_id"] = org_id

        if not merged.get("created_at"):
            merged["created_at"] = utc_now()
        merged["updated_at"] = utc_now()

        self.s3.write_json(key, merged)
        lk = LookupService(self.s3)
        lk.sync_organization_index_from_profile(merged)
        lk.sync_domains_from_profile(merged)

        # Update the centralized org index (single-file for fast listing)
        self._update_org_index(org_id, merged)

        return normalize_org(merged)

    def _update_org_index(self, org_id: str, profile: Dict[str, Any]) -> None:
        """Upsert an org entry in the centralized organizations index."""
        try:
            data = self.s3.read_json(ORG_INDEX_KEY) or {"organizations": []}
            orgs = data.get("organizations", [])
            orgs = [o for o in orgs if o.get("org_id") != org_id]
            orgs.append(profile)
            data["organizations"] = orgs
            self.s3.write_json(ORG_INDEX_KEY, data)
        except Exception:
            pass  # Non-critical — listing will fall back to per-file reads

    def _delete_from_org_index(self, org_id: str) -> None:
        """Remove an org from the centralized index."""
        try:
            data = self.s3.read_json(ORG_INDEX_KEY) or {"organizations": []}
            data["organizations"] = [o for o in data.get("organizations", []) if o.get("org_id") != org_id]
            self.s3.write_json(ORG_INDEX_KEY, data)
        except Exception:
            pass

    def upsert_org_profile(self, org_id: str, name: str, email: str, status: str = "pending") -> Dict:
        return self.merge_org_profile(org_id, {"name": name, "email": email, "status": status})

    def create_org(self, name: str, email: str, **kwargs) -> Dict[str, Any]:
        """Create a new organization with a ULID-based ID."""
        from app.pipeline.id_generator import generate_org_id
        org_id = generate_org_id()
        now = utc_now()
        profile = {
            "org_id": org_id,
            "name": name,
            "email": email,
            "status": kwargs.get("status", "pending"),
            "stage": "not_started",
            "created_at": now,
            "updated_at": now,
            **{k: v for k, v in kwargs.items() if k != "status"},
        }
        return self.merge_org_profile(org_id, profile)

    # ── Domain Lookup ────────────────────────────────────────────────────────

    def get_org_by_domain(self, domain: str) -> Optional[str]:
        data = self.s3.read_json(domain_lookup_key(str(domain).strip().lower()))
        if not data:
            return None
        return data.get("org_id")

    # ── Auditors ─────────────────────────────────────────────────────────────

    def get_auditors(self) -> List[Dict]:
        data = self.s3.read_json(auditor_master_key())
        return data if data else []

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
        return {"status": "success", "auditor_id": auditor_id, "org_id": org_id}

    # ── Org Listing ──────────────────────────────────────────────────────────

    def iter_org_ids(self) -> List[str]:
        prefix = "organizations/"
        seen: set[str] = set()
        out: List[str] = []
        token = None
        while True:
            params: Dict[str, Any] = {"Bucket": self.s3.bucket, "Prefix": prefix, "Delimiter": "/"}
            if token:
                params["ContinuationToken"] = token
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
                token = response.get("NextContinuationToken")
            else:
                break
        out.sort()
        return out

    def get_all_organizations(self, include_system_counts: bool = True) -> List[Dict]:
        """List all orgs from the centralized index (1 S3 read).

        Falls back to per-file reads if index doesn't exist.
        """
        # Fast path: read from centralized index
        data = self.s3.read_json(ORG_INDEX_KEY)
        if data and data.get("organizations"):
            results = []
            for profile in data["organizations"]:
                if include_system_counts:
                    profile.setdefault("ai_system_wip_count", 0)
                    profile.setdefault("ai_system_completed_count", 0)
                results.append(normalize_org(profile))
            results.sort(key=lambda x: (x.get("name") or x.get("org_id") or ""))
            return results

        # Slow fallback: per-file reads (first time before index exists)
        results: List[Dict] = []
        for org_id in self.iter_org_ids():
            profile = self.get_org_profile_raw(org_id) or {
                "org_id": org_id, "name": org_id, "email": None, "status": "pending",
            }
            if include_system_counts:
                profile.setdefault("ai_system_wip_count", 0)
                profile.setdefault("ai_system_completed_count", 0)
            results.append(normalize_org(profile))
        results.sort(key=lambda x: (x.get("name") or x.get("org_id") or ""))
        return results

    def list_organizations_filtered(
        self, *,
        onboarded_by: Optional[str] = None,
        onboarded_by_id: Optional[str] = None,
        org_type: Optional[str] = None,
        org_types: Optional[List[str]] = None,
        aict_approved: Optional[bool] = None,
        stage: Optional[str] = None,
        status: Optional[str] = None,
        archived: Optional[bool] = None,
        q: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
        include_system_counts: bool = True,
    ) -> tuple[List[Dict], int]:
        all_rows = self.get_all_organizations(include_system_counts=include_system_counts)
        filtered = [
            o for o in all_rows
            if org_matches_filters(
                o, onboarded_by=onboarded_by, onboarded_by_id=onboarded_by_id,
                org_type=org_type, org_types=org_types, aict_approved=aict_approved,
                stage=stage, status=status, archived=archived, q=q,
            )
        ]
        page_rows, total = paginate(filtered, page, page_size)
        return page_rows, total

    def onboarding_decision(self, org_id: str, decision: str, email: Optional[str] = None, reason: Optional[str] = None) -> Dict[str, Any]:
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

    # ── Projects ─────────────────────────────────────────────────────────────

    def create_project(self, org_id: str, project_name: str, project_id: str = None) -> Dict[str, Any]:
        """Create a project with sequential ID (001, 002, ...)."""
        if not project_id:
            from app.pipeline.id_generator import next_project_seq
            project_id = next_project_seq(self.s3, org_id)
        now = utc_now()
        doc = {
            "project_id": project_id,
            "project_name": project_name,
            "org_id": org_id,
            "created_at": now,
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
            params: Dict[str, Any] = {"Bucket": self.s3.bucket, "Prefix": prefix, "Delimiter": "/"}
            if token:
                params["ContinuationToken"] = token
            resp = self.s3.client.list_objects_v2(**params)
            for cp in resp.get("CommonPrefixes", []):
                p = cp.get("Prefix", "").rstrip("/").split("/")[-1]
                if p:
                    out.append(p)
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
        out.sort()
        return out

    # ── AI Systems (nested folder structure) ─────────────────────────────────

    def list_ai_systems(self, org_id: str) -> List[Dict[str, Any]]:
        """List AI systems by scanning nested project/systems folders.

        Falls back to legacy org-level ai_systems.json if no nested structure found.
        """
        systems: List[Dict[str, Any]] = []
        project_ids = self.list_project_ids(org_id)

        for pid in project_ids:
            prefix = systems_prefix(org_id, pid)
            token = None
            while True:
                params: Dict[str, Any] = {"Bucket": self.s3.bucket, "Prefix": prefix, "Delimiter": "/"}
                if token:
                    params["ContinuationToken"] = token
                resp = self.s3.client.list_objects_v2(**params)
                for cp in resp.get("CommonPrefixes", []):
                    sid = cp.get("Prefix", "").rstrip("/").split("/")[-1]
                    if not sid:
                        continue
                    sys_doc = self.s3.read_json(system_json_key(org_id, pid, sid))
                    if sys_doc:
                        sys_doc["project_id"] = pid
                        systems.append(sys_doc)
                    else:
                        systems.append({
                            "system_id": sid, "ai_system_id": sid,
                            "org_id": org_id, "project_id": pid,
                            "name": sid, "status": "wip",
                        })
                if resp.get("IsTruncated"):
                    token = resp.get("NextContinuationToken")
                else:
                    break

        # Fallback: legacy flat ai_systems.json
        if not systems:
            legacy_key = f"organizations/{org_id}/ai_systems.json"
            raw = self.s3.read_json(legacy_key)
            if raw and raw.get("systems"):
                systems = list(raw["systems"])

        return systems

    def add_ai_system(self, org_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Add an AI system with sequential ID under the specified project.

        Auto-creates project if project_id not provided.
        Creates the audit folder with composite audit ID.
        """
        from app.pipeline.id_generator import next_system_seq

        project_id = body.get("project_id")
        project_name = body.get("project_name", "")

        # Auto-create project if needed
        if not project_id:
            proj = self.create_project(org_id, project_name or "Default Project")
            project_id = proj["project_id"]
        else:
            # Ensure project.json exists
            existing_proj = self.get_project(org_id, project_id)
            if not existing_proj:
                self.create_project(org_id, project_name or f"Project {project_id}", project_id=project_id)

        # Generate sequential system ID
        system_id = body.get("system_id") or body.get("ai_system_id")
        if not system_id:
            system_id = next_system_seq(self.s3, org_id, project_id)

        now = utc_now()
        audit_id = body.get("audit_id") or new_audit_ulid()

        # Write system.json
        sys_doc = {
            "ai_system_id": system_id,
            "system_id": system_id,
            "name": body.get("name", system_id),
            "description": body.get("description", ""),
            "version": body.get("version", "v1"),
            "status": body.get("status", "wip"),
            "org_id": org_id,
            "project_id": project_id,
            "audit_id": audit_id,
            "manager_id": body.get("manager_id"),
            "manager_name": body.get("manager_name", ""),
            "practitioner_id": body.get("practitioner_id"),
            "practitioner_name": body.get("practitioner_name", ""),
            "created_at": now,
            "added_at": now,
        }
        self.s3.write_json(system_json_key(org_id, project_id, system_id), sys_doc)

        AuditLifecycleService(self.s3).create_audit(
            org_id,
            project_id,
            system_id,
            auditor_id=body.get("auditor_id") or "system",
            audit_id=audit_id,
        )

        # Update system count in org profile (avoids scanning on list)
        profile = self.get_org_profile_raw(org_id) or {}
        profile["ai_system_wip_count"] = (profile.get("ai_system_wip_count") or 0) + 1
        self.merge_org_profile(org_id, {
            "ai_system_wip_count": profile["ai_system_wip_count"],
            "ai_system_completed_count": profile.get("ai_system_completed_count", 0),
        })

        return sys_doc

    def update_ai_system(self, org_id: str, project_id: str, system_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Update fields on an existing system.json."""
        key = system_json_key(org_id, project_id, system_id)
        existing = self.s3.read_json(key)
        if not existing:
            raise ValueError(f"System not found: {org_id}/{project_id}/{system_id}")
        existing.update(patch)
        existing["updated_at"] = utc_now()
        self.s3.write_json(key, existing)
        return existing

    def filter_ai_systems(self, org_id: str, *, status: Optional[str] = None, stage: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self.list_ai_systems(org_id)
        out = []
        for s in rows:
            if status and (s.get("status") or "") != status:
                continue
            if stage and (s.get("stage") or "") != stage:
                continue
            out.append(s)
        return out
