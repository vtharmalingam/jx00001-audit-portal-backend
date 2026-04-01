"""Request bodies and LLM output schema for ``/api/v1/knowledge``."""

from typing import List

from pydantic import BaseModel, Field, confloat


class SemanticSearchBody(BaseModel):
    context: str = Field(..., description="Query / context text.")
    count: int = Field(default=10, ge=1, le=200)


class GapAnalysisBody(BaseModel):
    index_name: str
    question: str
    user_answer: str
    customer_id: str = ""
    question_id: str = ""


class SynthesisGapOutput(BaseModel):
    synthesized_summary: str = Field(
        description="Reference answer from retrieved context only."
    )
    key_themes: List[str] = Field(min_length=1)
    user_gap: List[str] = Field(
        description="Factual gaps vs synthesized_summary."
    )
    insights: List[str] = Field(description="Actionable guidance.")
    match_score: confloat(ge=0.0, le=1.0) = Field(
        description="Alignment score derived from content coverage."
    )
