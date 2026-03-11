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


def test_gap_report_empty(real_s3):
    org_id = "org_unit_test"
    audit_id = "audit_unit_test"

    service = ReportService(real_s3)

    result = service.get_gap_report(org_id, audit_id)

    assert result == []


def test_gap_report_with_data(real_s3):
    org_id = "org_unit_test"
    audit_id = "audit_unit_test"

    service = ReportService(real_s3)

    # Seed AI data
    real_s3.write_json(
        ai_key(org_id, audit_id, "Q1"),
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
        ai_key(org_id, audit_id, "Q2"),
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

    result = service.get_gap_report(org_id, audit_id)

    assert len(result) == 2

    # Ensure sorted order
    assert result[0]["question_id"] == "Q1"
    assert result[1]["question_id"] == "Q2"


def test_gap_report_ignores_corrupt_entries(real_s3):
    org_id = "org_unit_test"
    audit_id = "audit_unit_test"

    service = ReportService(real_s3)

    # valid entry
    real_s3.write_json(
        ai_key(org_id, audit_id, "Q1"),
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

    # corrupt (None)
    real_s3.store[
        ai_key(org_id, audit_id, "Q2")
    ] = None

    result = service.get_gap_report(org_id, audit_id)

    assert len(result) == 1
    assert result[0]["question_id"] == "Q1"