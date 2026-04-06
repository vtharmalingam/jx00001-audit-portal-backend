"""
Purpose: Audit control plane — create audit, metadata.json, timeline events, audit_summary
recompute, wiring to answers/AI/auditor keys; core audit folder lifecycle.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.etl.s3.utils.helpers import utc_now
from app.etl.s3.utils.ids import new_audit_ulid

from app.etl.s3.utils.s3_paths import (
    ai_key,
    answers_index_key,
    answers_prefix,
    audit_metadata_key,
    audit_summary_key,
    auditor_key,
    timeline_key,
)
from app.etl.s3.services.lookup_service import LookupService


def _empty_audit_summary() -> Dict[str, Any]:
    return {
        "total_questions": 0,
        "answered": 0,
        "ai_processed": 0,
        "reviewed": 0,
        "compliant": 0,
        "non_compliant": 0,
        "needs_revision": 0,
    }


class AuditLifecycleService:
    def __init__(self, s3):
        self.s3 = s3

    def create_audit(
        self,
        org_id: str,
        project_id: str,
        ai_system_id: str,
        *,
        auditor_id: str = "unknown",
        audit_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        aid = audit_id or new_audit_ulid()
        now = utc_now()
        meta = {
            "audit_id": aid,
            "org_id": org_id,
            "project_id": project_id,
            "ai_system_id": ai_system_id,
            "auditor_id": auditor_id,
            "status": "in_progress",
            "current_round": 1,
            "started_at": now,
            "last_updated_at": now,
            "completed_at": None,
        }
        self.s3.write_json(
            audit_metadata_key(org_id, aid, project_id, ai_system_id),
            meta,
        )
        self.s3.write_json(
            audit_summary_key(org_id, aid, project_id, ai_system_id),
            _empty_audit_summary(),
        )
        self.s3.write_json(
            timeline_key(org_id, aid, project_id, ai_system_id),
            {
                "events": [
                    {
                        "timestamp": now,
                        "actor": "system",
                        "action": "audit_created",
                        "audit_id": aid,
                    }
                ]
            },
        )
        LookupService(self.s3).write_ai_system_index(
            ai_system_id,
            org_id=org_id,
            project_id=project_id,
            audit_id=aid,
            status="in_progress",
        )
        return meta

    def get_metadata(
        self,
        org_id: str,
        audit_id: str,
        project_id: str,
        ai_system_id: str,
    ) -> Optional[Dict[str, Any]]:
        return self.s3.read_json(
            audit_metadata_key(org_id, audit_id, project_id, ai_system_id)
        )

    def patch_metadata(
        self,
        org_id: str,
        audit_id: str,
        patch: Dict[str, Any],
        project_id: str,
        ai_system_id: str,
    ) -> Dict[str, Any]:
        key = audit_metadata_key(org_id, audit_id, project_id, ai_system_id)
        cur = self.s3.read_json(key) or {}
        merged = {**cur, **patch}
        merged["audit_id"] = audit_id
        merged["org_id"] = org_id
        merged["last_updated_at"] = utc_now()
        self.s3.write_json(key, merged)
        return merged

    def append_timeline_event(
        self,
        org_id: str,
        audit_id: str,
        event: Dict[str, Any],
        project_id: str,
        ai_system_id: str,
    ) -> Dict[str, Any]:
        key = timeline_key(org_id, audit_id, project_id, ai_system_id)
        doc = self.s3.read_json(key) or {"events": []}
        events: List[Dict[str, Any]] = list(doc.get("events") or [])
        ev = {**event, "timestamp": event.get("timestamp") or utc_now()}
        events.append(ev)
        doc["events"] = events
        self.s3.write_json(key, doc)
        return doc

    def recompute_audit_summary(
        self,
        org_id: str,
        audit_id: str,
        project_id: str,
        ai_system_id: str,
        total_questions_hint: Optional[int] = None,
    ) -> Dict[str, Any]:
        from app.etl.s3.services.derived_service import schedule_derived_recompute

        answered = 0
        ai_processed = 0
        reviewed = 0
        compliant = 0
        non_compliant = 0
        needs_revision = 0
        qids: List[str] = []

        idx_doc = self.s3.read_json(answers_index_key(org_id, audit_id, project_id, ai_system_id))
        idx_items = idx_doc.get("items") if isinstance(idx_doc, dict) else None
        use_index = (
            isinstance(idx_items, list)
            and len(idx_items) > 0
            and all(isinstance(i, dict) and i.get("question_id") for i in idx_items)
        )

        if use_index:
            for it in idx_items:
                qid = str(it.get("question_id") or "")
                if not qid:
                    continue
                qids.append(qid)
                st = it.get("state")
                if st in ("submitted", "locked"):
                    answered += 1
                ver = int(it.get("version") or 0)
                ai = self.s3.read_json(
                    ai_key(org_id, audit_id, qid, project_id, ai_system_id)
                )
                if ai and int(ai.get("last_analyzed_version") or 0) >= ver and ver > 0:
                    ai_processed += 1
                aud = self.s3.read_json(
                    auditor_key(org_id, audit_id, qid, project_id, ai_system_id)
                )
                if aud and int(aud.get("reviewed_version") or 0) == ver and ver > 0:
                    reviewed += 1
                    rs = (aud.get("review_state") or "").lower()
                    if rs in ("compliant", "approved"):
                        compliant += 1
                    elif rs in ("non_compliant", "rejected"):
                        non_compliant += 1
                    elif rs == "needs_revision":
                        needs_revision += 1
        else:
            prefix = answers_prefix(org_id, audit_id, project_id, ai_system_id)
            token = None
            while True:
                params: Dict[str, Any] = {"Bucket": self.s3.bucket, "Prefix": prefix}
                if token:
                    params["ContinuationToken"] = token
                resp = self.s3.client.list_objects_v2(**params)
                for obj in resp.get("Contents", []):
                    k = obj["Key"]
                    if k.rstrip("/").endswith("_index.json"):
                        continue
                    if not k.endswith(".json"):
                        continue
                    data = self.s3.read_json(k)
                    if not data or "question_id" not in data:
                        continue
                    qid = data["question_id"]
                    qids.append(qid)
                    st = data.get("state")
                    if st in ("submitted", "locked"):
                        answered += 1
                    ver = int(data.get("version") or 0)
                    ai = self.s3.read_json(
                        ai_key(org_id, audit_id, qid, project_id, ai_system_id)
                    )
                    if ai and int(ai.get("last_analyzed_version") or 0) >= ver and ver > 0:
                        ai_processed += 1
                    aud = self.s3.read_json(
                        auditor_key(org_id, audit_id, qid, project_id, ai_system_id)
                    )
                    if aud and int(aud.get("reviewed_version") or 0) == ver and ver > 0:
                        reviewed += 1
                        rs = (aud.get("review_state") or "").lower()
                        if rs in ("compliant", "approved"):
                            compliant += 1
                        elif rs in ("non_compliant", "rejected"):
                            non_compliant += 1
                        elif rs == "needs_revision":
                            needs_revision += 1
                if resp.get("IsTruncated"):
                    token = resp.get("NextContinuationToken")
                else:
                    break

        distinct = len(set(qids))
        total = total_questions_hint if total_questions_hint is not None else distinct
        summary = {
            "total_questions": total,
            "answered": answered,
            "ai_processed": ai_processed,
            "reviewed": reviewed,
            "compliant": compliant,
            "non_compliant": non_compliant,
            "needs_revision": needs_revision,
            "recomputed_at": utc_now(),
        }
        self.s3.write_json(
            audit_summary_key(org_id, audit_id, project_id, ai_system_id),
            summary,
        )
        try:
            schedule_derived_recompute(self.s3, org_id, audit_id, project_id, ai_system_id)
        except Exception:
            pass
        return summary

    def touch_after_mutation(
        self,
        org_id: str,
        audit_id: str,
        *,
        project_id: str,
        ai_system_id: str,
        action: str,
        question_id: Optional[str] = None,
        version: Optional[int] = None,
        actor: str = "user",
        recompute_summary: bool = True,
        append_timeline: bool = True,
    ) -> None:
        meta_key = audit_metadata_key(org_id, audit_id, project_id, ai_system_id)
        cur = self.s3.read_json(meta_key)
        if cur:
            cur = dict(cur)
            cur["last_updated_at"] = utc_now()
            self.s3.write_json(meta_key, cur)
        if append_timeline:
            ev: Dict[str, Any] = {"actor": actor, "action": action}
            if question_id:
                ev["question_id"] = question_id
            if version is not None:
                ev["version"] = version
            self.append_timeline_event(org_id, audit_id, ev, project_id, ai_system_id)
        if recompute_summary:
            try:
                self.recompute_audit_summary(org_id, audit_id, project_id, ai_system_id)
            except Exception:
                pass
