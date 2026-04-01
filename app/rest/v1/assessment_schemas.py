"""Request bodies for ``/api/v1/assessment`` routes."""

from typing import Optional

from pydantic import BaseModel, Field


class EvaluateAnswerBody(BaseModel):
    q_id: str
    user_answer: str
    category: Optional[str] = None


class SaveAnswerBody(BaseModel):
    question_id: str
    user_answer: str
    org_id: str = "0"
    sys_id: str = "0"
    state: str = "draft"


class SaveReviewBody(BaseModel):
    org_id: str
    audit_id: str = "0"
    question_id: str
    review_state: str
    reviewer_comment: Optional[str] = None
    auditor_id: Optional[str] = Field(
        default=None,
        description="Replaces former WebSocket client_id for feedback attribution.",
    )
