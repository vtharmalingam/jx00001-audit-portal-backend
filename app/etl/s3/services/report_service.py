"""
Purpose: Read-side reporting — full audit view assembly, gap / AI analysis listing from
stored AI blobs, aggregates for dashboards.
"""

from typing import Dict, List

from app.etl.s3.utils.s3_paths import ai_key, auditor_key, evidence_index_key


class ReportService:

    def __init__(self, s3):
        self.s3 = s3

    def get_full_audit_view(
        self,
        org_id: str,
        audit_id: str,
        project_id: str,
        ai_system_id: str,
    ) -> Dict:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from app.etl.s3.utils.s3_paths import answers_prefix

        # Load evidence index once — authoritative source for uploaded files.
        raw_ev = self.s3.read_json(evidence_index_key(org_id, audit_id, project_id, ai_system_id)) or {}
        evidence_by_qid: Dict[str, List[Dict]] = {
            str(qid): items for qid, items in raw_ev.items() if isinstance(items, list)
        }

        prefix = answers_prefix(org_id, audit_id, project_id, ai_system_id)

        # Collect all answer S3 keys first (fast — just metadata listing)
        answer_keys: List[str] = []
        continuation_token = None
        while True:
            params = {"Bucket": self.s3.bucket, "Prefix": prefix}
            if continuation_token:
                params["ContinuationToken"] = continuation_token
            response = self.s3.client.list_objects_v2(**params)
            for obj in response.get("Contents", []):
                k = obj["Key"]
                if not k.rstrip("/").endswith("_index.json"):
                    answer_keys.append(k)
            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        def fetch_question(answer_key: str):
            """Read answer + AI analysis + auditor review for one question in parallel."""
            answer = self.s3.read_json(answer_key)
            if not answer:
                return None
            qid = answer.get("question_id")
            if not qid:
                return None

            # Merge answer.json attachments with evidence_index entries,
            # deduplicating by s3_key so files uploaded either way appear once.
            ans_attachments = answer.get("attachments") or []
            ev_attachments = evidence_by_qid.get(str(qid), [])
            seen: set = set()
            merged_attachments = []
            for att in [*ans_attachments, *ev_attachments]:
                key = att.get("s3_key") or att.get("file_name", "")
                if key and key not in seen:
                    seen.add(key)
                    merged_attachments.append(att)

            item = {
                "question_id": qid,
                "answer": answer.get("answer"),
                "attachments": merged_attachments,
            }

            ai = self.s3.read_json(ai_key(org_id, audit_id, qid, project_id, ai_system_id))
            if ai:
                item["gap_report"] = ai.get("gap_report", {})
                item["risk_level"] = ai.get("risk_level")

            auditor = self.s3.read_json(auditor_key(org_id, audit_id, qid, project_id, ai_system_id))
            if auditor:
                item["review"] = {
                    "review_state": auditor.get("review_state"),
                    "reviewer_comment": auditor.get("summary"),
                    "reviewed_at": auditor.get("reviewed_at"),
                    "reviewer_id": auditor.get("auditor_id"),
                    "recommendations": auditor.get("recommendations") or [],
                }

            return qid, item

        result = {}
        if answer_keys:
            max_workers = min(32, len(answer_keys))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(fetch_question, k): k for k in answer_keys}
                for future in as_completed(futures):
                    try:
                        out = future.result()
                        if out:
                            qid, item = out
                            result[qid] = item
                    except Exception as exc:
                        import logging as _log
                        _log.getLogger(__name__).warning("fetch_question failed: %s", exc)

        return {
            "org_id": org_id,
            "audit_id": audit_id,
            "project_id": project_id,
            "ai_system_id": ai_system_id,
            "data": result,
        }

    def get_gap_report(
        self,
        org_id: str,
        audit_id: str,
        project_id: str,
        ai_system_id: str,
    ) -> List[Dict]:
        from app.etl.s3.utils.s3_paths import ai_prefix

        prefix = ai_prefix(org_id, audit_id, project_id, ai_system_id)

        results = []

        continuation_token = None

        while True:
            params = {
                "Bucket": self.s3.bucket,
                "Prefix": prefix,
            }

            if continuation_token:
                params["ContinuationToken"] = continuation_token

            response = self.s3.client.list_objects_v2(**params)

            contents = response.get("Contents", [])

            for obj in contents:
                k = obj["Key"]
                if k.rstrip("/").endswith("_index.json"):
                    continue
                data = self.s3.read_json(k)
                if data and data.get("question_id"):
                    results.append(data)

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        results.sort(key=lambda x: x.get("question_id", ""))

        return results
