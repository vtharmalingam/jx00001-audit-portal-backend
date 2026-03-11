# services/ai_service.py

from datetime import datetime
from typing import Dict, Optional
from app.etl.s3.utils.s3_paths import ai_key


class AIService:

    def __init__(self, s3, llm):
        self.s3 = s3
        self.llm = llm


    # automated AI
    def process_org(
        self,
        org_id: str,
        audit_id: str,
        question_id: Optional[str] = None
    ) -> Dict:

        prefix = f"organizations/{org_id}/audits/{audit_id}/current/answers/"

        processed = 0
        skipped = 0
        failed = 0

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
                    skipped += 1
                    continue

                qid = answer.get("question_id")

                # 🔹 Filter by specific question if provided
                if question_id and qid != question_id:
                    continue

                # 🔹 Only process submitted answers
                if answer.get("state") != "submitted":
                    skipped += 1
                    continue

                version = answer.get("version", 0)

                # 🔹 Fetch existing AI result
                ai = self.s3.read_json(
                    ai_key(org_id, audit_id, qid)
                )

                if ai and ai.get("last_analyzed_version", 0) >= version:
                    skipped += 1
                    continue

                try:
                    # 🔹 Call LLM
                    result = self.llm.analyze(answer.get("answer", ""))

                    if not isinstance(result, dict):
                        raise ValueError("Invalid AI response format")

                    ai_data = {
                        "question_id": qid,
                        "last_analyzed_version": version,
                        "analyzed_at": datetime.utcnow().isoformat(),
                        **result
                    }

                    self.s3.write_json(
                        ai_key(org_id, audit_id, qid),
                        ai_data
                    )

                    processed += 1

                except Exception as e:
                    failed += 1
                    # Optional: log error
                    print(f"[AI ERROR] {qid}: {str(e)}")

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        return {
            "processed": processed,
            "skipped": skipped,
            "failed": failed
        }


    # manual override
    def upsert_ai_analysis(
        self,
        org_id: str,
        audit_id: str,
        question_id: str,
        ai_payload: Dict
    ) -> Dict:
        """
        Directly write AI analysis (override mode).
        No dependency on answer state.
        """

        if not question_id:
            raise ValueError("question_id is required")

        if not isinstance(ai_payload, dict):
            raise ValueError("ai_payload must be a dictionary")

        # 🔹 Optional: fetch answer to align version
        answer_key_path = f"organizations/{org_id}/audits/{audit_id}/current/answers/{question_id}.json"
        answer = self.s3.read_json(answer_key_path)

        version = 0
        if answer:
            version = answer.get("version", 0)

        ai_data = {
            "question_id": question_id,
            "last_analyzed_version": version,
            "analyzed_at": datetime.utcnow().isoformat(),
            **ai_payload
        }

        self.s3.write_json(
            ai_key(org_id, audit_id, question_id),
            ai_data
        )

        return ai_data        
    

if __name__ == "__main__":

    from app.etl.s3.services.s3_client import S3Client

    # 🔹 CONFIG (adjust if needed)
    BUCKET = "audit-system-data"

    org_id = "D01"
    audit_id = "0"
    question_id = "Q1_3"

    # 🔹 Initialize S3 + Service
    s3 = S3Client(BUCKET)

    # LLM not needed for manual override
    ai_service = AIService(s3=s3, llm=None)

    # 🔹 Sample AI payload
    ai_payload = {
      "question_id": "Q1_3",
      "last_analyzed_version": 1,
      "analyzed_at": "2026-02-23T06:10:00Z",
      "risk_level": "high",
      "gap_report": {
        "synthesized_summary": "The response provides only generic and high-level bypass scenarios with minimal detail and lacks any concrete detection strategy or technical depth.",
        "key_themes": [
          "generic bypass scenarios",
          "weak detection strategy",
          "lack of technical depth",
          "insufficient audit readiness"
        ],
        "user_gap": [
          "Bypass scenarios are vague and not tied to specific system architecture or threat models",
          "No explanation of how detection mechanisms actually work",
          "Lacks mention of tools, logs, alerts, or monitoring systems used",
          "No discussion of response actions or mitigation once a bypass is detected",
          "Does not quantify risk or likelihood of bypass scenarios"
        ],
        "insights": [
          "Response appears superficial and not suitable for audit-level scrutiny",
          "Detection capability is weakly defined and relies on generic monitoring",
          "No evidence of structured threat modeling or security testing",
          "Indicates potential gaps in security maturity and control effectiveness"
        ],
        "match_score": 0.35
      }
    }

    print("\n🚀 Running AI manual override test...\n")

    try:
        result = ai_service.upsert_ai_analysis(
            org_id=org_id,
            audit_id=audit_id,
            question_id=question_id,
            ai_payload=ai_payload
        )

        print("✅ AI Analysis written successfully:\n")
        print(result)

    except Exception as e:
        print(f"❌ Error: {str(e)}")    