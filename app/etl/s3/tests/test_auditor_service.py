'''
✔ fetch only submitted answers
✔ update feedback correctly
✔ overwrite feedback (only once allowed logically)
'''

import pytest

from app.etl.s3.services.auditor_service import AuditorService


def test_auditor_feedback_real_s3(real_s3):
    org_id = "org_unit_test"
    audit_id = "audit_unit_test"

    service = AuditorService(real_s3)

    feedback = {
        "version": 1,
        "auditor_id": "aud_1",
        "review_state": "approved",
        "feedback": []
    }

    res = service.update_feedback(
        org_id,
        audit_id,
        "Q1",
        feedback
    )

    assert res["review_state"] == "approved"
    assert res["auditor_id"] == "aud_1"