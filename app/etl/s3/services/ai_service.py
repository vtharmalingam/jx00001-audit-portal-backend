# services/ai_service.py

from typing import Dict, Optional

from app.etl.s3.utils.helpers import utc_now

from app.etl.s3.services.audit_lifecycle_service import AuditLifecycleService
from app.etl.s3.utils.s3_paths import ai_key, answer_key, answers_prefix


class AIService:

    def __init__(self, s3, llm):
        self.s3 = s3
        self.llm = llm

    def process_org(
        self,
        org_id: str,
        audit_id: str,
        question_id: Optional[str] = None,
        project_id: str = "0",
        ai_system_id: str = "0",
    ) -> Dict:

        prefix = answers_prefix(org_id, audit_id, project_id, ai_system_id)

        processed = 0
        skipped = 0
        failed = 0
        lifecycle = AuditLifecycleService(self.s3)

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
                answer = self.s3.read_json(obj["Key"])

                if not answer:
                    skipped += 1
                    continue

                qid = answer.get("question_id")

                if question_id and qid != question_id:
                    continue

                if answer.get("state") != "submitted":
                    skipped += 1
                    continue

                version = answer.get("version", 0)

                ai = self.s3.read_json(
                    ai_key(org_id, audit_id, qid, project_id, ai_system_id)
                )

                if ai and ai.get("last_analyzed_version", 0) >= version:
                    skipped += 1
                    continue

                try:
                    result = self.llm.analyze(answer.get("answer", ""))

                    if not isinstance(result, dict):
                        raise ValueError("Invalid AI response format")

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

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        if processed:
            try:
                lifecycle.recompute_audit_summary(
                    org_id, audit_id, project_id, ai_system_id
                )
            except Exception:
                pass

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
        project_id: str = "0",
        ai_system_id: str = "0",
    ) -> Dict:

        if not question_id:
            raise ValueError("question_id is required")

        if not isinstance(ai_payload, dict):
            raise ValueError("ai_payload must be a dictionary")

        answer_key_path = answer_key(
            org_id, audit_id, question_id, project_id, ai_system_id
        )
        answer = self.s3.read_json(answer_key_path)

        version = 0
        if answer:
            version = answer.get("version", 0)

        ai_data = {
            "question_id": question_id,
            "last_analyzed_version": version,
            "analyzed_at": utc_now(),
            **ai_payload,
        }

        self.s3.write_json(
            ai_key(org_id, audit_id, question_id, project_id, ai_system_id),
            ai_data,
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

        return ai_data


if __name__ == "__main__":

    from app.etl.s3.services.s3_client import S3Client

    BUCKET = "audit-system-data"

    org_id = "D01"
    audit_id = "0"
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
        )
        print(result)
    except Exception as e:
        print(f"Error: {str(e)}")
