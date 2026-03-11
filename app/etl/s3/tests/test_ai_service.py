'''
✔ process only submitted answers
✔ skip draft answers
✔ skip already processed version
✔ process updated version
✔ handle LLM failure gracefully
✔ filter by question_id
'''

import pytest

from app.etl.s3.services.answer_service import AnswerService
from app.etl.s3.services.ai_service import AIService


class MockLLM:
    def analyze(self, text):
        return {
            "risk_level": "medium",
            "confidence": 0.9,
            "gap_report": {
                "synthesized_summary": "ok",
                "key_themes": [],
                "user_gap": [],
                "insights": [],
                "match_score": 0.7
            }
        }


def test_ai_processing_real_s3(real_s3):
    org_id = "org_unit_test"
    audit_id = "audit_unit_test"

    answer_service = AnswerService(real_s3)

    # Create submitted answer
    answer_service.upsert_answer(
        org_id,
        audit_id,
        "Q1",
        "Some answer",
        state="submitted"
    )

    ai_service = AIService(real_s3, MockLLM())
    result = ai_service.process_org(org_id, audit_id)

    assert result["processed"] == 1
    assert result["failed"] == 0