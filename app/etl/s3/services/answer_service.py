# services/answer_service.py

from typing import Dict, List, Optional

from app.etl.s3.utils.helpers import utc_now

from app.etl.s3.services.audit_lifecycle_service import AuditLifecycleService
from app.etl.s3.utils.s3_paths import answer_key, answers_prefix


class AnswerService:

    def __init__(self, s3):
        self.s3 = s3

    def get_all_answers(
        self,
        org_id: str,
        audit_id: str,
        project_id: str = "0",
        ai_system_id: str = "0",
    ) -> List[Dict]:

        prefix = answers_prefix(org_id, audit_id, project_id, ai_system_id)

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

            for obj in response.get("Contents", []):
                data = self.s3.read_json(obj["Key"])

                if data and "question_id" in data:
                    results.append(data)

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        results.sort(key=lambda x: x.get("question_id", ""))

        return results

    def upsert_answer(
        self,
        org_id: str,
        audit_id: str,
        question_id: str,
        answer: str,
        state: str = "draft",
        user: str = "system",
        project_id: str = "0",
        ai_system_id: str = "0",
    ) -> Dict:

        key = answer_key(org_id, audit_id, question_id, project_id, ai_system_id)

        existing = self.s3.read_json(key)

        version = 1
        if existing and "version" in existing:
            version = existing["version"] + 1

        attachments = existing.get("attachments") if isinstance(existing, dict) else None
        if not isinstance(attachments, list):
            attachments = []

        data = {
            "question_id": question_id,
            "answer": answer,
            "state": state,
            "version": version,
            "attachments": attachments,
            "last_updated_at": utc_now(),
            "last_updated_by": user,
        }

        self.s3.write_json(key, data)
        AuditLifecycleService(self.s3).touch_after_mutation(
            org_id,
            audit_id,
            project_id=project_id,
            ai_system_id=ai_system_id,
            action="updated_answer",
            question_id=question_id,
            version=version,
            actor=user,
        )
        return data

    def get_answer(
        self,
        org_id: str,
        audit_id: str,
        question_id: str,
        project_id: str = "0",
        ai_system_id: str = "0",
    ) -> Optional[Dict]:

        return self.s3.read_json(
            answer_key(org_id, audit_id, question_id, project_id, ai_system_id)
        )
