# services/report_service.py

from typing import List, Dict
from app.etl.s3.utils.s3_paths import ai_key  # optional if needed later
from app.etl.s3.utils.s3_paths import answer_key, ai_key, auditor_key

class ReportService:

    def __init__(self, s3):
        self.s3 = s3



    def get_full_audit_view(self, org_id: str, audit_id: str) -> Dict:

        prefix = f"organizations/{org_id}/audits/{audit_id}/current/answers/"

        result = {}
        continuation_token = None

        while True:
            params = {
                "Bucket": self.s3.bucket,
                "Prefix": prefix
            }

            if continuation_token:
                params["ContinuationToken"] = continuation_token

            response = self.s3.client.list_objects_v2(**params)

            for obj in response.get("Contents", []):
                answer = self.s3.read_json(obj["Key"])

                if not answer:
                    continue

                qid = answer.get("question_id")
                if not qid:
                    continue

                # 🔹 Base structure
                item = {
                    "question_id": qid,
                    "answer": answer.get("answer"),
                }

                # 🔹 AI Layer
                ai = self.s3.read_json(ai_key(org_id, audit_id, qid))
                if ai:
                    item["gap_report"] = ai.get("gap_report", {})
                    item["risk_level"] = ai.get("risk_level")

                # 🔹 Auditor Layer
                auditor = self.s3.read_json(auditor_key(org_id, audit_id, qid))
                if auditor:
                    item["review"] = {
                        "review_state": auditor.get("review_state"),
                        "reviewer_comment": auditor.get("summary"),
                        "reviewed_at": auditor.get("reviewed_at"),
                        "reviewer_id": auditor.get("auditor_id"),
                    }

                result[qid] = item

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        return {
            "org_id": org_id,
            "audit_id": audit_id,
            "data": result
        }


    # OBSOLETED
    # This method can be obsoleted inview of the above - that inclues additional details too.
    def get_gap_report(self, org_id: str, audit_id: str) -> List[Dict]:
        prefix = f"organizations/{org_id}/audits/{audit_id}/current/ai_analysis/"

        results = []

        continuation_token = None

        while True:
            params = {
                "Bucket": self.s3.bucket,
                "Prefix": prefix
            }

            if continuation_token:
                params["ContinuationToken"] = continuation_token

            response = self.s3.client.list_objects_v2(**params)

            contents = response.get("Contents", [])

            for obj in contents:
                data = self.s3.read_json(obj["Key"])
                if data:
                    results.append(data)

            # Handle pagination
            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        # Optional: sort by question_id (useful for UI consistency)
        results.sort(key=lambda x: x.get("question_id", ""))

        return results


