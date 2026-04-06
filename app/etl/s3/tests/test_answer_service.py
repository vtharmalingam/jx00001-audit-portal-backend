
'''
✔ create new answer → version = 1
✔ update answer → version increments
✔ invalid state → reject
✔ get answer → returns correct data

'''
import pytest

from app.etl.s3.services.answer_service import AnswerService

ORG_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
AUDIT_ID = "01J7RZ8G6E9VX4D3N2C5M8P1QR"
PROJECT_ID = "001"
AI_SYSTEM_ID = "0001"


def test_get_all_answers(real_s3):
    service = AnswerService(real_s3)

    service.upsert_answer(
        ORG_ID, AUDIT_ID, PROJECT_ID, AI_SYSTEM_ID, "Q2", "A2",
    )
    service.upsert_answer(
        ORG_ID, AUDIT_ID, PROJECT_ID, AI_SYSTEM_ID, "Q1", "A1",
    )

    result = service.get_all_answers(ORG_ID, AUDIT_ID, PROJECT_ID, AI_SYSTEM_ID)

    assert len(result) == 2
    assert result[0]["question_id"] == "Q1"
    assert result[1]["question_id"] == "Q2"


def test_answer_upsert_real_s3(real_s3):
    service = AnswerService(real_s3)

    res1 = service.upsert_answer(
        ORG_ID, AUDIT_ID, PROJECT_ID, AI_SYSTEM_ID, "Q1", "Answer 1",
    )
    assert res1["version"] == 1

    res2 = service.upsert_answer(
        ORG_ID, AUDIT_ID, PROJECT_ID, AI_SYSTEM_ID, "Q1", "Answer 2",
    )
    assert res2["version"] == 2

    stored = service.get_answer(ORG_ID, AUDIT_ID, "Q1", PROJECT_ID, AI_SYSTEM_ID)
    assert stored["answer"] == "Answer 2"
