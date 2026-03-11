# services/answer_service.py

from datetime import datetime
from typing import Optional, Dict, List
from app.etl.s3.utils.s3_paths import answer_key


class AnswerService:

    def __init__(self, s3):
        self.s3 = s3


    def get_all_answers(
        self,
        org_id: str,
        audit_id: str
    ) -> List[Dict]:

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

                if data and "question_id" in data:
                    results.append(data)

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        # Sort for UI consistency
        results.sort(key=lambda x: x.get("question_id", ""))

        return results

    # 🔹 A. Upsert Answer
    def upsert_answer(
        self,
        org_id: str,
        audit_id: str,
        question_id: str,
        answer: str,
        state: str = "draft",
        user: str = "system"
    ) -> Dict:

        key = answer_key(org_id, audit_id, question_id)

        existing = self.s3.read_json(key)

        version = 1
        if existing and "version" in existing:
            version = existing["version"] + 1

        data = {
            "question_id": question_id,
            "answer": answer,
            "state": state,  # draft | submitted | locked (i think locked maynot be required)
            "version": version,
            "last_updated_at": datetime.utcnow().isoformat(),
            "last_updated_by": user
        }

        self.s3.write_json(key, data)
        return data

    # 🔹 B. Get Answer
    def get_answer(
        self,
        org_id: str,
        audit_id: str,
        question_id: str
    ) -> Optional[Dict]:

        return self.s3.read_json(
            answer_key(org_id, audit_id, question_id)
        )

