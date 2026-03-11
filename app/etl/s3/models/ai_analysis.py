# models/ai_analysis.py

from pydantic import BaseModel, Field
from typing import List, Literal


class GapReport(BaseModel):
    synthesized_summary: str
    key_themes: List[str]
    user_gap: List[str]
    insights: List[str]
    match_score: float = Field(ge=0.0, le=1.0)


class AIAnalysisModel(BaseModel):
    question_id: str

    last_analyzed_version: int
    analyzed_at: str

    risk_level: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0.0, le=1.0)

    gap_report: GapReport