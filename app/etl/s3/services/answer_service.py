"""
Purpose: Assessment answers under the v2 audit path — list all answer JSON for a scope,
upsert single answers; coordinates with audit lifecycle where needed.
"""

from typing import Dict, List, Optional

from app.etl.s3.utils.helpers import utc_now

from app.etl.s3.services.audit_lifecycle_service import AuditLifecycleService
from app.etl.s3.services.current_index import sync_answers_index
from app.etl.s3.utils.s3_paths import answer_key, answers_index_key, answers_prefix


class AnswerService:

    def __init__(self, s3):
        self.s3 = s3

    def get_all_answers(
        self,
        org_id: str,
        audit_id: str,
        project_id: str,
        ai_system_id: str,
    ) -> List[Dict]:
        # Step 1 — Prefer answers/_index.json when present (avoids full prefix listing).
        idx_doc = self.s3.read_json(answers_index_key(org_id, audit_id, project_id, ai_system_id))
        idx_items = idx_doc.get("items") if isinstance(idx_doc, dict) else None
        if isinstance(idx_items, list) and idx_items and all(
            isinstance(i, dict) and i.get("question_id") for i in idx_items
        ):
            results: List[Dict] = []
            seen = set()
            for it in sorted(idx_items, key=lambda x: str(x.get("question_id") or "")):
                qid = str(it.get("question_id") or "")
                if not qid or qid in seen:
                    continue
                seen.add(qid)
                data = self.s3.read_json(
                    answer_key(org_id, audit_id, qid, project_id, ai_system_id)
                )
                if data and "question_id" in data:
                    results.append(data)
            return results

        # Step 2 — Fallback: list prefix for all per-question answer JSON objects.
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
                k = obj["Key"]
                if k.rstrip("/").endswith("_index.json"):
                    continue
                data = self.s3.read_json(k)

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
        project_id: str,
        ai_system_id: str,
        question_id: str,
        answer: str,
        state: str = "draft",
        user: str = "system",
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
        sync_answers_index(
            self.s3,
            org_id,
            audit_id,
            question_id=question_id,
            version=version,
            state=state,
            project_id=project_id,
            ai_system_id=ai_system_id,
        )
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

    def bulk_set_state(
        self,
        org_id: str,
        audit_id: str,
        project_id: str,
        ai_system_id: str,
        answers: List[Dict],
        new_state: str = "submitted",
    ) -> int:
        """
        Batch-update state on pre-fetched answers. Writes each answer JSON
        and rebuilds the index once at the end — much faster than calling
        upsert_answer per question (skips per-answer index sync and lifecycle).
        """
        now = utc_now()
        count = 0
        index_items = []

        for ans in answers:
            qid = ans.get("question_id")
            if not qid:
                continue
            key = answer_key(org_id, audit_id, qid, project_id, ai_system_id)
            version = (ans.get("version") or 0) + 1
            attachments = ans.get("attachments") if isinstance(ans, dict) else None
            if not isinstance(attachments, list):
                attachments = []
            data = {
                "question_id": qid,
                "answer": ans.get("answer", ""),
                "state": new_state,
                "version": version,
                "attachments": attachments,
                "last_updated_at": now,
                "last_updated_by": "system",
            }
            self.s3.write_json(key, data)
            index_items.append({"question_id": qid, "version": version, "state": new_state})
            count += 1

        # Rebuild index once
        if index_items:
            idx_key = answers_index_key(org_id, audit_id, project_id, ai_system_id)
            self.s3.write_json(idx_key, {"items": index_items, "updated_at": now})

        # Single lifecycle event for the whole submission
        if count > 0:
            AuditLifecycleService(self.s3).touch_after_mutation(
                org_id, audit_id,
                project_id=project_id,
                ai_system_id=ai_system_id,
                action="bulk_submitted",
                question_id=f"{count}_questions",
                version=0,
                actor="system",
            )
        return count

    def get_answer(
        self,
        org_id: str,
        audit_id: str,
        question_id: str,
        project_id: str,
        ai_system_id: str,
    ) -> Optional[Dict]:
        # Step 1 — Direct GetObject for one question; None if the answer file does not exist.
        return self.s3.read_json(
            answer_key(org_id, audit_id, question_id, project_id, ai_system_id)
        )
