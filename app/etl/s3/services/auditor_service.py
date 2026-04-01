# services/auditor_service.py

from datetime import datetime
from typing import Dict, List, Optional

from app.etl.s3.services.audit_lifecycle_service import AuditLifecycleService
from app.etl.s3.utils.s3_paths import answers_prefix, auditor_key


class AuditorService:

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
                if data and data.get("state") == "submitted":
                    results.append(data)

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        return results

    def update_feedback(
        self,
        org_id: str,
        audit_id: str,
        question_id: str,
        feedback: Dict,
        project_id: str = "0",
        ai_system_id: str = "0",
    ) -> Dict:

        key = auditor_key(org_id, audit_id, question_id, project_id, ai_system_id)

        fb_list = feedback.get("feedback")
        if not isinstance(fb_list, list):
            fb_list = []
        recs = feedback.get("recommendations")
        if not isinstance(recs, list):
            recs = []

        data = {
            "question_id": question_id,
            "reviewed_version": feedback["version"],
            "reviewed_at": datetime.utcnow().isoformat(),
            "auditor_id": feedback["auditor_id"],
            "auditor_name": feedback.get("auditor_name"),
            "review_state": feedback["review_state"],
            "summary": feedback.get("summary"),
            "feedback": fb_list,
            "recommendations": recs,
        }

        self.s3.write_json(key, data)
        AuditLifecycleService(self.s3).touch_after_mutation(
            org_id,
            audit_id,
            project_id=project_id,
            ai_system_id=ai_system_id,
            action="auditor_review",
            question_id=question_id,
            version=feedback.get("version"),
            actor=str(feedback.get("auditor_id") or "auditor"),
        )
        return data
