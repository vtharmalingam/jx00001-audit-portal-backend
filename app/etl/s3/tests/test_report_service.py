'''
✔ returns empty list when no AI data
✔ returns all AI analysis objects
✔ ignores missing/corrupt objects
✔ maintains stable ordering (sorted by question_id)
✔ works with multiple questions
'''

import pytest

from app.etl.s3.services.report_service import ReportService
from app.etl.s3.utils.s3_paths import ai_key

ORG_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
AUDIT_ID = "01J7RZ8G6E9VX4D3N2C5M8P1QR"
PROJECT_ID = "001"
AI_SYSTEM_ID = "0001"


def test_gap_report_empty(real_s3):
    service = ReportService(real_s3)

    result = service.get_gap_report(ORG_ID, AUDIT_ID, PROJECT_ID, AI_SYSTEM_ID)

    assert result == []


def test_gap_report_with_data(real_s3):
    service = ReportService(real_s3)

    real_s3.write_json(
        ai_key(ORG_ID, AUDIT_ID, "Q1", PROJECT_ID, AI_SYSTEM_ID),
        {
            "question_id": "Q1",
            "last_analyzed_version": 1,
            "analyzed_at": "2026-01-01T00:00:00Z",
            "risk_level": "medium",
            "confidence": 0.8,
            "gap_report": {
                "synthesized_summary": "summary",
                "key_themes": [],
                "user_gap": [],
                "insights": [],
                "match_score": 0.6
            }
        }
    )

    real_s3.write_json(
        ai_key(ORG_ID, AUDIT_ID, "Q2", PROJECT_ID, AI_SYSTEM_ID),
        {
            "question_id": "Q2",
            "last_analyzed_version": 1,
            "analyzed_at": "2026-01-01T00:00:00Z",
            "risk_level": "high",
            "confidence": 0.9,
            "gap_report": {
                "synthesized_summary": "summary2",
                "key_themes": [],
                "user_gap": [],
                "insights": [],
                "match_score": 0.4
            }
        }
    )

    result = service.get_gap_report(ORG_ID, AUDIT_ID, PROJECT_ID, AI_SYSTEM_ID)

    assert len(result) == 2

    assert result[0]["question_id"] == "Q1"
    assert result[1]["question_id"] == "Q2"


def test_gap_report_ignores_corrupt_entries(real_s3):
    service = ReportService(real_s3)

    real_s3.write_json(
        ai_key(ORG_ID, AUDIT_ID, "Q1", PROJECT_ID, AI_SYSTEM_ID),
        {
            "question_id": "Q1",
            "last_analyzed_version": 1,
            "analyzed_at": "2026-01-01T00:00:00Z",
            "risk_level": "low",
            "confidence": 0.7,
            "gap_report": {
                "synthesized_summary": "ok",
                "key_themes": [],
                "user_gap": [],
                "insights": [],
                "match_score": 0.9
            }
        }
    )

    real_s3.put_bytes(
        ai_key(ORG_ID, AUDIT_ID, "Q2", PROJECT_ID, AI_SYSTEM_ID),
        b"not valid json {{{",
    )

    result = service.get_gap_report(ORG_ID, AUDIT_ID, PROJECT_ID, AI_SYSTEM_ID)

    assert len(result) == 1
    assert result[0]["question_id"] == "Q1"
