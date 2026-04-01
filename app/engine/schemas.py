from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class BaseRequest(BaseModel):
    reqType: str
    reqSubType: str
    reqData: Optional[Dict[str, Any]] = Field(default_factory=dict)


# --- Per-handler ``reqData`` bodies (HTTP OpenAPI + validation) ----------------
class EmptyReqData(BaseModel):
    """No required fields; matches handlers that do not read ``reqData``."""

    model_config = ConfigDict(extra="allow")


class GetQuestionsReqData(BaseModel):
    """``reqData`` for ``AI-ASSESSMENT-REQ`` / ``GET-QUESTIONS``."""

    category: str = Field(..., description="Question category key to load.")


class EvaluateAnswerReqData(BaseModel):
    """``reqData`` for ``AI-ASSESSMENT-REQ`` / ``EVALUATE-ANSWER``."""

    q_id: str = Field(..., description="Question identifier.")
    user_answer: str = Field(..., description="User answer text to score.")
    category: Optional[str] = Field(
        default=None,
        description="Optional category id (metadata/UI; handler does not require it).",
    )


class SaveAnswerReqData(BaseModel):
    """``reqData`` for ``AI-ASSESSMENT-REQ`` / ``SAVE-ANSWER``."""

    question_id: str = Field(..., description="Question id (maps to ``q_id`` in service).")
    user_answer: str = Field(..., description="Answer text to store.")
    org_id: str = Field(default="0", description="Organization id.")
    sys_id: str = Field(default="0", description="System id (optional metadata).")
    state: str = Field(default="draft", description="e.g. draft / submitted.")


class FetchAnswersReqData(BaseModel):
    """``reqData`` for ``AI-ASSESSMENT-REQ`` / ``FETCH-ANSWERS``."""

    org_id: str = Field(..., description="Organization id.")
    audit_id: str = Field(
        default="0",
        description="Audit id (handler may still use a fixed audit for now).",
    )


class SaveOrgProfileReqData(BaseModel):
    """``reqData`` for ``AI-ASSESSMENT-REQ`` / ``SAVE-ORG-PROFILE``."""

    org_id: str = Field(...)
    name: str = Field(...)
    email: str = Field(...)
    status: str = Field(default="pending", description="Org onboarding status.")


class FetchFullAuditReqData(BaseModel):
    """``reqData`` for ``FETCH-FULL-AUDIT`` and ``FETCH-GAP-ANALYSIS``."""

    org_id: str = Field(...)
    audit_id: str = Field(default="0")


class SaveReviewReqData(BaseModel):
    """``reqData`` for ``AI-ASSESSMENT-REQ`` / ``SAVE-REVIEW``."""

    org_id: str = Field(...)
    audit_id: str = Field(default="0")
    question_id: str = Field(...)
    review_state: str = Field(...)
    reviewer_comment: Optional[str] = Field(
        default=None, description="Optional comment stored on feedback."
    )


class SummarySemanticSearchReqData(BaseModel):
    """``reqData`` for ``SUPPORTWIZ_USER_REQS`` / ``SUMMARY-SEMANTIC-SEARCH``."""

    context: str = Field(
        ...,
        description="Context / query text for semantic search (was mis-labeled QUERY in legacy errors).",
    )
    count: int = Field(
        default=10,
        ge=1,
        description="Number of results (default 10).",
    )


class UserAnswerGapAnalysisReqData(BaseModel):
    """``reqData`` for ``SUPPORTWIZ_USER_REQS`` / ``USER-ANSWER-GAP-ANALYSIS``."""

    index_name: str = Field(...)
    question: str = Field(...)
    user_answer: str = Field(...)
    customer_id: str = Field(default="", description="Echoed in response when provided.")
    question_id: str = Field(default="", description="Echoed in response when provided.")


# Maps (reqType, reqSubType) → body model for OpenAPI ``/api/handlers/...`` routes.
ROUTE_OPENAPI_BODIES: dict[tuple[str, str], type[BaseModel]] = {
    ("AI-ASSESSMENT-REQ", "GET-CATEGORIES"): EmptyReqData,
    ("AI-ASSESSMENT-REQ", "GET-QUESTIONS"): GetQuestionsReqData,
    ("AI-ASSESSMENT-REQ", "EVALUATE-ANSWER"): EvaluateAnswerReqData,
    ("AI-ASSESSMENT-REQ", "SAVE-ANSWER"): SaveAnswerReqData,
    ("AI-ASSESSMENT-REQ", "FETCH-ANSWERS"): FetchAnswersReqData,
    ("AI-ASSESSMENT-REQ", "SAVE-ORG-PROFILE"): SaveOrgProfileReqData,
    ("AI-ASSESSMENT-REQ", "FETCH-ORGANIZATIONS"): EmptyReqData,
    ("AI-ASSESSMENT-REQ", "FETCH-FULL-AUDIT"): FetchFullAuditReqData,
    ("AI-ASSESSMENT-REQ", "FETCH-GAP-ANALYSIS"): FetchFullAuditReqData,
    ("AI-ASSESSMENT-REQ", "SAVE-REVIEW"): SaveReviewReqData,
    ("SUPPORTWIZ_USER_REQS", "SUMMARY-SEMANTIC-SEARCH"): SummarySemanticSearchReqData,
    ("SUPPORTWIZ_USER_REQS", "USER-ANSWER-GAP-ANALYSIS"): UserAnswerGapAnalysisReqData,
}
