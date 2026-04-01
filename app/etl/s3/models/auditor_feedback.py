# models/auditor_feedback.py

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


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
        "compliant",
        "non_compliant",
        "approved",
        "rejected",
    ]

    summary: Optional[str]

    feedback: List[FeedbackItem]
    recommendations: List[str] = Field(default_factory=list)