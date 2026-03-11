# models/auditor_feedback.py

from pydantic import BaseModel
from typing import List, Literal, Optional


class FeedbackItem(BaseModel):
    type: str
    message: str
    severity: Literal["low", "medium", "high", "critical"]


class AuditorFeedbackModel(BaseModel):
    question_id: str

    reviewed_version: int
    reviewed_at: str

    auditor_id: str

    review_state: Literal[
        "not_reviewed",
        "in_review",
        "needs_revision",
        "approved",
        "rejected"
    ]

    summary: Optional[str]

    feedback: List[FeedbackItem]