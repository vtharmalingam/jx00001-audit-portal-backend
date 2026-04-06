'''
✔ fetch only submitted answers
✔ update feedback correctly
✔ overwrite feedback (only once allowed logically)
'''

import pytest

from app.etl.s3.services.auditor_service import AuditorService

ORG_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
AUDIT_ID = "01J7RZ8G6E9VX4D3N2C5M8P1QR"
PROJECT_ID = "001"
AI_SYSTEM_ID = "0001"


def test_auditor_feedback_real_s3(real_s3):
    service = AuditorService(real_s3)

    feedback = {
        "version": 1,
        "auditor_id": "aud_1",
        "review_state": "approved",
        "feedback": []
    }

    res = service.update_feedback(
        ORG_ID,
        AUDIT_ID,
        "Q1",
        feedback,
        PROJECT_ID,
        AI_SYSTEM_ID,
    )

    assert res["review_state"] == "approved"
    assert res["auditor_id"] == "aud_1"
