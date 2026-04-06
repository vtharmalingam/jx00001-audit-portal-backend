"""
Purpose: Evidence attachments — evidence index per audit scope, register evidence objects
(metadata and optional file payload keys).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.etl.s3.utils.helpers import utc_now

from app.etl.s3.utils.s3_paths import evidence_index_key, evidence_object_key
from app.etl.s3.services.audit_lifecycle_service import AuditLifecycleService


class EvidenceService:
    def __init__(self, s3):
        self.s3 = s3

    def _load_index(
        self,
        org_id: str,
        audit_id: str,
        project_id: str,
        ai_system_id: str,
    ) -> Dict[str, List[Dict[str, Any]]]:
        key = evidence_index_key(org_id, audit_id, project_id, ai_system_id)
        raw = self.s3.read_json(key)
        if not raw or not isinstance(raw, dict):
            return {}
        out: Dict[str, List[Dict[str, Any]]] = {}
        for qid, items in raw.items():
            if isinstance(items, list):
                out[str(qid)] = list(items)
        return out

    def _save_index(
        self,
        org_id: str,
        audit_id: str,
        project_id: str,
        ai_system_id: str,
        index: Dict[str, List[Dict[str, Any]]],
    ) -> None:
        self.s3.write_json(
            evidence_index_key(org_id, audit_id, project_id, ai_system_id),
            index,
        )

    def register_evidence(
        self,
        org_id: str,
        audit_id: str,
        question_id: str,
        *,
        file_name: str,
        s3_key: Optional[str] = None,
        uploaded_by: str = "unknown",
        project_id: str,
        ai_system_id: str,
        body: Optional[bytes] = None,
        content_type: str = "application/octet-stream",
    ) -> Dict[str, Any]:
        key = s3_key or evidence_object_key(
            org_id, audit_id, question_id, file_name, project_id, ai_system_id
        )
        if body is not None:
            self.s3.put_bytes(key, body, content_type=content_type)

        now = utc_now()
        entry = {
            "file_name": file_name,
            "s3_key": key,
            "uploaded_by": uploaded_by,
            "uploaded_at": now,
        }

        index = self._load_index(org_id, audit_id, project_id, ai_system_id)
        bucket = index.setdefault(question_id, [])
        bucket.append(entry)
        self._save_index(org_id, audit_id, project_id, ai_system_id, index)

        from app.etl.s3.utils.s3_paths import answer_key

        ans_key = answer_key(
            org_id, audit_id, question_id, project_id, ai_system_id
        )
        ans = self.s3.read_json(ans_key)
        if ans:
            atts = ans.get("attachments")
            if not isinstance(atts, list):
                atts = []
            atts.append(
                {
                    "file_name": file_name,
                    "s3_key": key,
                    "uploaded_at": now,
                }
            )
            ans["attachments"] = atts
            self.s3.write_json(ans_key, ans)

        AuditLifecycleService(self.s3).touch_after_mutation(
            org_id,
            audit_id,
            project_id=project_id,
            ai_system_id=ai_system_id,
            action="evidence_uploaded",
            question_id=question_id,
            actor=uploaded_by,
        )
        return entry

    def list_index(
        self,
        org_id: str,
        audit_id: str,
        project_id: str,
        ai_system_id: str,
    ) -> Dict[str, List[Dict[str, Any]]]:
        return self._load_index(org_id, audit_id, project_id, ai_system_id)
