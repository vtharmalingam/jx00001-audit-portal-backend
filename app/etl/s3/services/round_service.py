# services/round_service.py

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.etl.s3.utils.s3_paths import (
    ai_prefix,
    answers_prefix,
    audit_metadata_key,
    auditor_key,
    current_prefix,
    round_prefix,
)


class RoundService:
    def __init__(self, s3):
        self.s3 = s3

    def create_round_snapshot(
        self,
        org_id: str,
        audit_id: str,
        round_n: int,
        *,
        project_id: str = "0",
        ai_system_id: str = "0",
        trigger: str = "manual",
        triggered_by: str = "system",
        notes: str = "",
    ) -> Dict[str, Any]:
        dest = round_prefix(org_id, audit_id, round_n, project_id, ai_system_id)

        answers_map: Dict[str, Any] = {}
        prefix_a = answers_prefix(org_id, audit_id, project_id, ai_system_id)
        token = None
        while True:
            params: Dict[str, Any] = {"Bucket": self.s3.bucket, "Prefix": prefix_a}
            if token:
                params["ContinuationToken"] = token
            resp = self.s3.client.list_objects_v2(**params)
            for obj in resp.get("Contents", []):
                if not obj["Key"].endswith(".json"):
                    continue
                row = self.s3.read_json(obj["Key"])
                if row and row.get("question_id"):
                    answers_map[row["question_id"]] = row
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break

        ai_map: Dict[str, Any] = {}
        prefix_i = ai_prefix(org_id, audit_id, project_id, ai_system_id)
        token = None
        while True:
            params = {"Bucket": self.s3.bucket, "Prefix": prefix_i}
            if token:
                params["ContinuationToken"] = token
            resp = self.s3.client.list_objects_v2(**params)
            for obj in resp.get("Contents", []):
                if not obj["Key"].endswith(".json"):
                    continue
                row = self.s3.read_json(obj["Key"])
                if row and row.get("question_id"):
                    ai_map[row["question_id"]] = row
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break

        fb_map: Dict[str, Any] = {}
        for qid in set(answers_map) | set(ai_map):
            row = self.s3.read_json(
                auditor_key(org_id, audit_id, qid, project_id, ai_system_id)
            )
            if row:
                fb_map[qid] = row

        self.s3.write_json(f"{dest}answers.json", answers_map)
        self.s3.write_json(f"{dest}ai_analysis.json", ai_map)
        self.s3.write_json(f"{dest}auditor_feedback.json", fb_map)

        ev_root = f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/evidence/"
        token = None
        while True:
            params = {"Bucket": self.s3.bucket, "Prefix": ev_root}
            if token:
                params["ContinuationToken"] = token
            resp = self.s3.client.list_objects_v2(**params)
            for obj in resp.get("Contents", []):
                sk = obj["Key"]
                if sk.endswith("/"):
                    continue
                rel = sk[len(ev_root) :]
                dk = f"{dest}evidence/{rel}"
                self.s3.copy_object(sk, dk)
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break

        summary = {
            "round": int(round_n),
            "trigger": trigger,
            "triggered_by": triggered_by,
            "notes": notes,
            "snapshot_at": datetime.utcnow().isoformat(),
        }
        self.s3.write_json(f"{dest}round_summary.json", summary)

        meta_key = audit_metadata_key(org_id, audit_id, project_id, ai_system_id)
        meta = self.s3.read_json(meta_key)
        if meta:
            meta = dict(meta)
            meta["current_round"] = max(int(meta.get("current_round") or 1), int(round_n))
            meta["last_updated_at"] = datetime.utcnow().isoformat()
            self.s3.write_json(meta_key, meta)

        return {"round": round_n, "destination_prefix": dest, "round_summary": summary}
