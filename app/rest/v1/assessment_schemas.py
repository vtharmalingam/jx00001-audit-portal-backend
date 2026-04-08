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
    org_id: str
    state: str = "draft"
    audit_id: str
    project_id: str
    ai_system_id: str


class SaveReviewBody(BaseModel):
    org_id: str
    audit_id: str
    project_id: str
    ai_system_id: str
    question_id: str
    review_state: str
    reviewer_comment: Optional[str] = None
    auditor_id: Optional[str] = Field(
        default=None,
        description="Auditor id for feedback attribution.",
    )
    auditor_name: Optional[str] = None
    recommendations: Optional[List[str]] = None


class CreateCategoryBody(BaseModel):
    category_id: str
    display_name: str
    description: str = ""
    status: Optional[str] = "draft"
    control_id: Optional[str] = None


class UpdateCategoryBody(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    category_id: Optional[str] = None
    control_id: Optional[str] = None


class CreateQuestionBody(BaseModel):
    question_id: str
    question: str
    category_id: str
    placeholder: Optional[str] = ""
    coverage_dimensions: Optional[List[str]] = Field(default_factory=list)


class UpdateQuestionBody(BaseModel):
    question: Optional[str] = None
    category_id: Optional[str] = None
    placeholder: Optional[str] = None
    coverage_dimensions: Optional[List[str]] = None
    question_id: Optional[str] = None


class EvidenceRegisterBody(BaseModel):
    org_id: str
    audit_id: str
    question_id: str
    file_name: str
    project_id: str
    ai_system_id: str
    uploaded_by: str = "system"
    content_base64: Optional[str] = None
    s3_key_override: Optional[str] = None

    @field_validator("content_base64")
    @classmethod
    def strip_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        return v


class EvidenceBatchItem(BaseModel):
    file_name: str
    content_base64: str


class EvidenceBatchBody(BaseModel):
    org_id: str
    audit_id: str
    question_id: str
    project_id: str
    ai_system_id: str
    uploaded_by: str = "practitioner"
    files: List[EvidenceBatchItem]
