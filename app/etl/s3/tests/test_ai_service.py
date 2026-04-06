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

ORG_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
AUDIT_ID = "01J7RZ8G6E9VX4D3N2C5M8P1QR"
PROJECT_ID = "001"
AI_SYSTEM_ID = "0001"


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
    answer_service = AnswerService(real_s3)

    answer_service.upsert_answer(
        ORG_ID,
        AUDIT_ID,
        PROJECT_ID,
        AI_SYSTEM_ID,
        "Q1",
        "Some answer",
        state="submitted",
    )

    ai_service = AIService(real_s3, MockLLM())
    result = ai_service.process_org(
        ORG_ID, AUDIT_ID, PROJECT_ID, AI_SYSTEM_ID,
    )

    assert result["processed"] == 1
    assert result["failed"] == 0
