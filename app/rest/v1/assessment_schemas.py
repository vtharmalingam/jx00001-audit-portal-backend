"""Request bodies for ``/api/v1/assessment`` routes."""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class EvaluateAnswerBody(BaseModel):
    q_id: str
    user_answer: str
    category: Optional[str] = None


class SaveAnswerBody(BaseModel):
    question_id: str
    user_answer: str
    org_id: str = "0"
    state: str = "draft"
    audit_id: str = "0"
    project_id: str = "0"
    ai_system_id: str = "0"


class SaveReviewBody(BaseModel):
    org_id: str
    audit_id: str = "0"
    project_id: str = "0"
    ai_system_id: str = "0"
    question_id: str
    review_state: str
    reviewer_comment: Optional[str] = None
    auditor_id: Optional[str] = Field(
        default=None,
        description="Auditor id for feedback attribution.",
    )
    auditor_name: Optional[str] = None
    recommendations: Optional[List[str]] = None


class EvidenceRegisterBody(BaseModel):
    org_id: str
    audit_id: str
    question_id: str
    file_name: str
    project_id: str = "0"
    ai_system_id: str = "0"
    uploaded_by: str = "system"
    content_base64: Optional[str] = None
    s3_key_override: Optional[str] = None

    @field_validator("content_base64")
    @classmethod
    def strip_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        return v
