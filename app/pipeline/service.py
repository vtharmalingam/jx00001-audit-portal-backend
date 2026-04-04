"""Pipeline service: state transitions, board queries, gap analysis orchestration.

All data is stored inside the audit folder:
  organizations/{org}/projects/{proj}/ai_systems/{sys}/audits/{audit_id}/current/
      pipeline.json          — pipeline state
      gap_report.json        — full gap analysis report
      ai_analysis/{qid}.json — per-question gap results
      review.json            — CSAP review data
"""

from typing import Any, Dict, List, Optional

from app.etl.s3.utils.helpers import utc_now

from app.etl.s3.services.s3_client import S3Client
from app.etl.s3.utils.s3_paths import (
    ai_key,
    gap_report_key,
    pipeline_key,
)
from app.pipeline.models import GapAnalysisStatus, PipelineStage, STAGE_ORDER

PIPELINE_INDEX_KEY = "indexes/pipeline_board_index.json"

# Map org.stage values to pipeline stages
_STAGE_MAP = {
    "not_started": PipelineStage.NOT_STARTED.value,
    "in_progress": PipelineStage.IN_PROGRESS.value,
    "ai_gap_analysis": PipelineStage.AI_GAP_ANALYSIS.value,
    "under_review": PipelineStage.UNDER_REVIEW.value,
    "review_complete": PipelineStage.REVIEW_COMPLETE.value,
    "completed": PipelineStage.UNDER_REVIEW.value,
}


class PipelineService:
    def __init__(self, s3: S3Client):
        self.s3 = s3

    # ── Pipeline Record (inside audit folder) ────────────────────────────────

    def get_record(self, org_id: str, project_id: str = "0", ai_system_id: str = "0") -> Optional[Dict]:
        audit_id = f"{org_id}-{project_id}-{ai_system_id}"
        return self.s3.read_json(pipeline_key(org_id, audit_id, project_id, ai_system_id))

    def upsert_record(self, data: Dict) -> Dict:
        org_id = data["org_id"]
        project_id = data.get("project_id", "0")
        ai_system_id = data.get("ai_system_id", "0")
        audit_id = data.get("audit_id") or f"{org_id}-{project_id}-{ai_system_id}"
        data["audit_id"] = audit_id
        data["updated_at"] = utc_now()
        if not data.get("created_at"):
            data["created_at"] = data["updated_at"]
        self.s3.write_json(pipeline_key(org_id, audit_id, project_id, ai_system_id), data)

        # Update pipeline board index
        self._update_board_index(data)

        return data

    def _update_board_index(self, entry: Dict) -> None:
        """Upsert a pipeline entry in the board index."""
        try:
            idx = self.s3.read_json(PIPELINE_INDEX_KEY) or {"items": []}
            items = idx.get("items", [])
            key = f"{entry.get('org_id')}|{entry.get('project_id','0')}|{entry.get('ai_system_id','0')}"
            items = [i for i in items if f"{i.get('org_id')}|{i.get('project_id','0')}|{i.get('ai_system_id','0')}" != key]
            items.append(entry)
            idx["items"] = items
            self.s3.write_json(PIPELINE_INDEX_KEY, idx)
        except Exception:
            pass

    def ensure_record(self, org_id: str, project_id: str = "0", ai_system_id: str = "0", **kwargs) -> Dict:
        existing = self.get_record(org_id, project_id, ai_system_id)
        if existing:
            if kwargs:
                existing.update(kwargs)
                return self.upsert_record(existing)
            return existing
        now = utc_now()
        rec = {
            "org_id": org_id,
            "project_id": project_id,
            "ai_system_id": ai_system_id,
            "audit_id": f"{org_id}-{project_id}-{ai_system_id}",
            "stage": PipelineStage.NOT_STARTED.value,
            "created_at": now,
            "updated_at": now,
            **kwargs,
        }
        return self.upsert_record(rec)

    def transition_stage(
        self, org_id: str, new_stage: PipelineStage,
        project_id: str = "0", ai_system_id: str = "0", **extra,
    ) -> Dict:
        rec = self.get_record(org_id, project_id, ai_system_id) or {}
        rec["org_id"] = org_id
        rec["project_id"] = project_id
        rec["ai_system_id"] = ai_system_id
        rec["stage"] = new_stage.value
        rec.update(extra)
        return self.upsert_record(rec)

    def update_gap_progress(
        self, org_id: str, project_id: str = "0", ai_system_id: str = "0",
        *, completed: int, total: int,
    ) -> Dict:
        rec = self.get_record(org_id, project_id, ai_system_id) or {}
        rec["org_id"] = org_id
        rec["project_id"] = project_id
        rec["ai_system_id"] = ai_system_id
        rec["gap_analysis_completed"] = completed
        rec["gap_analysis_total"] = total
        rec["gap_analysis_progress"] = int((completed / total) * 100) if total > 0 else 0

        if completed >= total and total > 0:
            rec["gap_analysis_status"] = GapAnalysisStatus.COMPLETED.value
            rec["gap_analysis_completed_at"] = utc_now()
            rec["stage"] = PipelineStage.UNDER_REVIEW.value
            rec["review_started_at"] = utc_now()
        return self.upsert_record(rec)

    # ── Gap Analysis Results (inside audit/current/) ─────────────────────────

    def save_gap_question_result(
        self, org_id: str, question_id: str, result: Dict,
        project_id: str = "0", ai_system_id: str = "0",
    ) -> None:
        audit_id = f"{org_id}-{project_id}-{ai_system_id}"
        result["saved_at"] = utc_now()
        self.s3.write_json(ai_key(org_id, audit_id, question_id, project_id, ai_system_id), result)

    def save_gap_report(
        self, org_id: str, report: Dict,
        project_id: str = "0", ai_system_id: str = "0",
    ) -> None:
        audit_id = f"{org_id}-{project_id}-{ai_system_id}"
        report["completed_at"] = utc_now()
        self.s3.write_json(gap_report_key(org_id, audit_id, project_id, ai_system_id), report)

    def get_gap_report(self, org_id: str, project_id: str = "0", ai_system_id: str = "0") -> Optional[Dict]:
        audit_id = f"{org_id}-{project_id}-{ai_system_id}"
        return self.s3.read_json(gap_report_key(org_id, audit_id, project_id, ai_system_id))

    def get_gap_question_result(
        self, org_id: str, question_id: str, project_id: str = "0", ai_system_id: str = "0",
    ) -> Optional[Dict]:
        audit_id = f"{org_id}-{project_id}-{ai_system_id}"
        return self.s3.read_json(ai_key(org_id, audit_id, question_id, project_id, ai_system_id))

    # ── Board (hydrate from orgs — NO full scan) ────────────────────────────

    def get_board(
        self, user_role: str, user_id: str, user_org_id: Optional[str] = None,
        scope: Optional[str] = None, scope_org_id: Optional[str] = None,
    ) -> List[Dict]:
        """Return pipeline items from the board index (1 S3 read) + org index filtering.

        Merges explicit pipeline records (from index) with org+system entries
        that don't have pipeline records yet (synthesized from org index).
        """
        from app.etl.s3.services.operational_service import OperationalService, ORG_INDEX_KEY
        tier = user_role.rsplit("_", 1)[0] if "_" in user_role else user_role

        # 1. Read both indexes (2 S3 reads total)
        pipe_idx = self.s3.read_json(PIPELINE_INDEX_KEY) or {"items": []}
        org_idx = self.s3.read_json(ORG_INDEX_KEY) or {"organizations": []}

        pipe_items = pipe_idx.get("items", [])
        all_orgs = org_idx.get("organizations", [])

        # 2. Filter orgs by role/scope
        from app.etl.s3.services.org_normalize import normalize_org, org_matches_filters
        orgs = [normalize_org(o) for o in all_orgs]

        if tier == "aict":
            if scope == "firm" and scope_org_id:
                orgs = [o for o in orgs if o.get("onboarded_by_id") == scope_org_id]
            elif scope == "individual" and scope_org_id:
                orgs = [o for o in orgs if o.get("org_id") == scope_org_id]
            elif scope == "aict":
                orgs = [o for o in orgs if (o.get("onboarded_by_type") or "") in ("aict", "aict-client", "")]
            # else: "all" — keep all orgs
        elif tier == "firm":
            if not user_org_id:
                return []
            orgs = [o for o in orgs if o.get("onboarded_by_id") == user_org_id]
        elif tier == "individual":
            if not user_org_id:
                return []
            orgs = [o for o in orgs if o.get("org_id") == user_org_id]
        else:
            return []

        org_ids = {o.get("org_id") for o in orgs}
        org_map = {o.get("org_id"): o for o in orgs}

        # 3. Collect pipeline items for these orgs
        items = []
        seen_keys = set()

        for item in pipe_items:
            oid = item.get("org_id", "")
            if oid not in org_ids:
                continue
            org = org_map.get(oid, {})
            item.setdefault("org_name", org.get("name", oid))
            item.setdefault("onboarded_by_type", org.get("onboarded_by_type", ""))
            key = f"{oid}|{item.get('project_id','0')}|{item.get('ai_system_id','0')}"
            seen_keys.add(key)
            items.append(item)

        # 4. Synthesize entries for orgs that have no pipeline records
        for org in orgs:
            oid = org.get("org_id", "")
            if not oid:
                continue
            # Check if any pipeline item exists for this org
            has_pipeline = any(k.startswith(f"{oid}|") for k in seen_keys)
            if not has_pipeline:
                stage = _STAGE_MAP.get(org.get("stage") or "not_started", PipelineStage.NOT_STARTED.value)
                items.append({
                    "org_id": oid,
                    "project_id": "0",
                    "ai_system_id": "0",
                    "audit_id": f"{oid}-0-0",
                    "org_name": org.get("name", oid),
                    "stage": stage,
                    "onboarded_by_type": org.get("onboarded_by_type", ""),
                    "created_at": org.get("created_at", ""),
                    "updated_at": org.get("updated_at", ""),
                })

        return items
