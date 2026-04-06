"""
Purpose: Batch AI processing — walk submitted answers, call injected LLM, write AI analysis
(ai_key) when versions warrant it; uses AuditLifecycleService for lifecycle hooks.
"""

from typing import Dict, Optional

from app.etl.s3.utils.helpers import utc_now

from app.etl.s3.services.audit_lifecycle_service import AuditLifecycleService
from app.etl.s3.services.current_index import sync_ai_analysis_index
from app.etl.s3.utils.s3_paths import ai_key, answer_key, answers_prefix


class AIService:

    def __init__(self, s3, llm):
        self.s3 = s3
        self.llm = llm

    def process_org(
        self,
        org_id: str,
        audit_id: str,
        project_id: str,
        ai_system_id: str,
        question_id: Optional[str] = None,
    ) -> Dict:
        
        # Step 1 — Point at the S3 folder where this audit’s answer JSON files live.
        prefix = answers_prefix(org_id, audit_id, project_id, ai_system_id)

        # Step 2 — Counters for the run; lifecycle helper updates timeline/summary hooks.
        processed = 0
        skipped = 0
        failed = 0
        lifecycle = AuditLifecycleService(self.s3)

        continuation_token = None

        # Step 3 — Walk every answer object under the prefix (paginated list_objects_v2).
        while True:
            params = {
                "Bucket": self.s3.bucket,
                "Prefix": prefix,
            }

            if continuation_token:
                params["ContinuationToken"] = continuation_token

            response = self.s3.client.list_objects_v2(**params)

            for obj in response.get("Contents", []):
                ok = obj["Key"]
                if ok.rstrip("/").endswith("_index.json"):
                    continue
                answer = self.s3.read_json(ok)

                if not answer:
                    skipped += 1
                    continue

                qid = answer.get("question_id")

                # Step 5 — Optional: only process a single question when question_id is set.
                if question_id and qid != question_id:
                    continue

                # Step 6 — AI only runs on submitted answers; drafts are skipped.
                if answer.get("state") != "submitted":
                    skipped += 1
                    continue

                version = answer.get("version", 0)

                # Step 7 — Skip if we already analyzed this answer version (idempotent).
                ai = self.s3.read_json(
                    ai_key(org_id, audit_id, qid, project_id, ai_system_id)
                )

                if ai and ai.get("last_analyzed_version", 0) >= version:
                    skipped += 1
                    continue

                try:
                    # Step 8 — Call the injected LLM on the answer text; expect a dict result.
                    result = self.llm.analyze(answer.get("answer", ""))

                    if not isinstance(result, dict):
                        raise ValueError("Invalid AI response format")

                    # Step 9 — Persist analysis under the standard ai_key for this question.
                    ai_data = {
                        "question_id": qid,
                        "last_analyzed_version": version,
                        "analyzed_at": utc_now(),
                        **result,
                    }

                    self.s3.write_json(
                        ai_key(org_id, audit_id, qid, project_id, ai_system_id),
                        ai_data,
                    )

                    # Step 10 — Record the event on the audit (summary recomputed once at end).
                    lifecycle.touch_after_mutation(
                        org_id,
                        audit_id,
                        project_id=project_id,
                        ai_system_id=ai_system_id,
                        action="ai_analyzed",
                        question_id=qid,
                        version=version,
                        actor="ai",
                        recompute_summary=False,
                    )

                    processed += 1

                except Exception as e:
                    failed += 1
                    print(f"[AI ERROR] {qid}: {str(e)}")

            # Step 11 — Continue listing if S3 returned a truncated page.
            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        # Step 12 — Refresh audit_summary.json once if at least one question was analyzed.
        if processed:
            try:
                lifecycle.recompute_audit_summary(
                    org_id, audit_id, project_id, ai_system_id
                )
            except Exception:
                pass

        # Step 13 — Return how many answers were analyzed vs skipped vs failed.
        return {
            "processed": processed,
            "skipped": skipped,
            "failed": failed,
        }

    def upsert_ai_analysis(
        self,
        org_id: str,
        audit_id: str,
        question_id: str,
        ai_payload: Dict,
        project_id: str,
        ai_system_id: str,
    ) -> Dict:
        # Step 1 — Ensure we have a target question and a dict payload (no LLM call here).
        if not question_id:
            raise ValueError("question_id is required")

        if not isinstance(ai_payload, dict):
            raise ValueError("ai_payload must be a dictionary")

        # Step 2 — Read the answer file so last_analyzed_version aligns with answer.version.
        answer_key_path = answer_key(
            org_id, audit_id, question_id, project_id, ai_system_id
        )
        answer = self.s3.read_json(answer_key_path)

        version = 0
        if answer:
            version = answer.get("version", 0)

        # Step 3 — Build the stored AI document (caller-supplied fields merged in).
        ai_data = {
            "question_id": question_id,
            "last_analyzed_version": version,
            "analyzed_at": utc_now(),
            **ai_payload,
        }

        # Step 4 — Write to S3 and append an ai_analyzed event on the audit timeline.
        self.s3.write_json(
            ai_key(org_id, audit_id, question_id, project_id, ai_system_id),
            ai_data,
        )
        sync_ai_analysis_index(
            self.s3,
            org_id,
            audit_id,
            question_id=question_id,
            last_analyzed_version=version,
            project_id=project_id,
            ai_system_id=ai_system_id,
        )
        AuditLifecycleService(self.s3).touch_after_mutation(
            org_id,
            audit_id,
            project_id=project_id,
            ai_system_id=ai_system_id,
            action="ai_analyzed",
            question_id=question_id,
            version=version,
            actor="ai",
        )

        # Step 5 — Return the same structure that was written (for API responses / scripts).
        return ai_data


if __name__ == "__main__":
    # Dev-only: wire S3 and call upsert_ai_analysis with a sample payload (no LLM).

    from app.etl.s3.services.s3_client import S3Client

    BUCKET = "audit-system-data"

    org_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    audit_id = "01J7RZ8G6E9VX4D3N2C5M8P1QR"
    project_id = "001"
    ai_system_id = "0001"
    question_id = "Q1_3"

    s3 = S3Client(BUCKET)

    ai_service = AIService(s3=s3, llm=None)

    ai_payload = {
        "question_id": "Q1_3",
        "last_analyzed_version": 1,
        "analyzed_at": "2026-02-23T06:10:00Z",
        "risk_level": "high",
        "gap_report": {
            "synthesized_summary": "summary",
            "key_themes": [],
            "user_gap": [],
            "insights": [],
            "match_score": 0.35,
        },
    }

    try:
        result = ai_service.upsert_ai_analysis(
            org_id=org_id,
            audit_id=audit_id,
            question_id=question_id,
            ai_payload=ai_payload,
            project_id=project_id,
            ai_system_id=ai_system_id,
        )
        print(result)
    except Exception as e:
        print(f"Error: {str(e)}")
