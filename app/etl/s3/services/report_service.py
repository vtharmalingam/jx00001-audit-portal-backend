"""
Purpose: Read-side reporting — full audit view assembly, gap / AI analysis listing from
stored AI blobs, aggregates for dashboards.
"""

from typing import Dict, List

from app.etl.s3.utils.s3_paths import ai_key, auditor_key


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

        from app.etl.s3.utils.s3_paths import answers_prefix

        prefix = answers_prefix(org_id, audit_id, project_id, ai_system_id)

        result = {}
        continuation_token = None

        while True:
            params = {
                "Bucket": self.s3.bucket,
                "Prefix": prefix,
            }

            if continuation_token:
                params["ContinuationToken"] = continuation_token

            response = self.s3.client.list_objects_v2(**params)

            for obj in response.get("Contents", []):
                k = obj["Key"]
                if k.rstrip("/").endswith("_index.json"):
                    continue
                answer = self.s3.read_json(k)

                if not answer:
                    continue

                qid = answer.get("question_id")
                if not qid:
                    continue

                item = {
                    "question_id": qid,
                    "answer": answer.get("answer"),
                    "attachments": answer.get("attachments") or [],
                }

                ai = self.s3.read_json(
                    ai_key(org_id, audit_id, qid, project_id, ai_system_id)
                )
                if ai:
                    item["gap_report"] = ai.get("gap_report", {})
                    item["risk_level"] = ai.get("risk_level")

                auditor = self.s3.read_json(
                    auditor_key(org_id, audit_id, qid, project_id, ai_system_id)
                )
                if auditor:
                    item["review"] = {
                        "review_state": auditor.get("review_state"),
                        "reviewer_comment": auditor.get("summary"),
                        "reviewed_at": auditor.get("reviewed_at"),
                        "reviewer_id": auditor.get("auditor_id"),
                        "recommendations": auditor.get("recommendations") or [],
                    }

                result[qid] = item

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

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
