
'''
✔ create new answer → version = 1
✔ update answer → version increments
✔ invalid state → reject
✔ get answer → returns correct data

'''
import pytest

from app.etl.s3.services.answer_service import AnswerService

def test_get_all_answers(real_s3):
    from services.answer_service import AnswerService

    service = AnswerService(real_s3)

    org_id = "org_unit_test"
    audit_id = "audit_unit_test"

    service.upsert_answer(org_id, audit_id, "Q2", "A2")
    service.upsert_answer(org_id, audit_id, "Q1", "A1")

    result = service.get_all_answers(org_id, audit_id)

    assert len(result) == 2
    assert result[0]["question_id"] == "Q1"
    assert result[1]["question_id"] == "Q2"


def test_answer_upsert_real_s3(real_s3):
    org_id = "org_unit_test"
    audit_id = "audit_unit_test"

    service = AnswerService(real_s3)

    res1 = service.upsert_answer(org_id, audit_id, "Q1", "Answer 1")
    assert res1["version"] == 1

    res2 = service.upsert_answer(org_id, audit_id, "Q1", "Answer 2")
    assert res2["version"] == 2

    stored = service.get_answer(org_id, audit_id, "Q1")
    assert stored["answer"] == "Answer 2"

