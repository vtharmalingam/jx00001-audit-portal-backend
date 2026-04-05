"""
Purpose: Assessment answers under the v2 audit path — list all answer JSON for a scope,
upsert single answers; coordinates with audit lifecycle where needed.
"""

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
        # Step 1 — S3 prefix for all per-question answer files under this audit scope.
        prefix = answers_prefix(org_id, audit_id, project_id, ai_system_id)

        results = []
        continuation_token = None

        # Step 2 — Paginate list_objects_v2 and collect valid answer JSON objects.
        while True:
            params = {
                "Bucket": self.s3.bucket,
                "Prefix": prefix,
            }

            if continuation_token:
                params["ContinuationToken"] = continuation_token

            response = self.s3.client.list_objects_v2(**params)

            for obj in response.get("Contents", []):
                # Step 3 — Load each key; keep only documents that look like answers.
                data = self.s3.read_json(obj["Key"])

                if data and "question_id" in data:
                    results.append(data)

            # Step 4 — Follow continuation token until the prefix is fully listed.
            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        # Step 5 — Stable order for UIs and reports (by question_id).
        results.sort(key=lambda x: x.get("question_id", ""))

        # Step 6 — Full list for the scope (may be empty).
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
        # Step 1 — One object per question: deterministic S3 key for this answer file.
        key = answer_key(org_id, audit_id, question_id, project_id, ai_system_id)

        # Step 2 — Merge semantics: read prior doc so we can bump version and keep attachments.
        existing = self.s3.read_json(key)

        version = 1
        if existing and "version" in existing:
            version = existing["version"] + 1

        attachments = existing.get("attachments") if isinstance(existing, dict) else None
        if not isinstance(attachments, list):
            attachments = []

        # Step 3 — Build the stored row (text, state, monotonic version, audit metadata).
        data = {
            "question_id": question_id,
            "answer": answer,
            "state": state,
            "version": version,
            "attachments": attachments,
            "last_updated_at": utc_now(),
            "last_updated_by": user,
        }

        # Step 4 — Persist answer JSON to S3.
        self.s3.write_json(key, data)
        # Step 5 — Record timeline / hooks on the audit (updated_answer).
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
        # Step 6 — Return the same payload that was written (API / callers).
        return data

    def get_answer(
        self,
        org_id: str,
        audit_id: str,
        question_id: str,
        project_id: str = "0",
        ai_system_id: str = "0",
    ) -> Optional[Dict]:
        # Step 1 — Direct GetObject for one question; None if the answer file does not exist.
        return self.s3.read_json(
            answer_key(org_id, audit_id, question_id, project_id, ai_system_id)
        )
