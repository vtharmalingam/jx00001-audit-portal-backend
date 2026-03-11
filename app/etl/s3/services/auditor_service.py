# services/auditor_service.py

from datetime import datetime
from typing import List, Dict
from app.etl.s3.utils.s3_paths import auditor_key


class AuditorService:

    def __init__(self, s3):
        self.s3 = s3

    # 🔹 A. Get all submitted answers
    def get_all_answers(self, org_id: str, audit_id: str) -> List[Dict]:

        prefix = f"organizations/{org_id}/audits/{audit_id}/current/answers/"

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

            for obj in response.get("Contents", []):
                data = self.s3.read_json(obj["Key"])
                if data and data.get("state") == "submitted":
                    results.append(data)

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        return results

    # 🔹 B. Update auditor feedback
    def update_feedback(
        self,
        org_id: str,
        audit_id: str,
        question_id: str,
        feedback: Dict
    ) -> Dict:

        key = auditor_key(org_id, audit_id, question_id)

        data = {
            "question_id": question_id,
            "reviewed_version": feedback["version"],
            "reviewed_at": datetime.utcnow().isoformat(),
            "auditor_id": feedback["auditor_id"],
            "review_state": feedback["review_state"],
            "summary": feedback.get("summary"),
            "feedback": feedback["feedback"]
        }

        self.s3.write_json(key, data)
        return data