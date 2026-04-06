"""Pipeline stage models and schemas."""

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class PipelineStage(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    AI_GAP_ANALYSIS = "ai_gap_analysis"
    UNDER_REVIEW = "under_review"
    REVIEW_COMPLETE = "review_complete"


STAGE_ORDER = [
    PipelineStage.NOT_STARTED,
    PipelineStage.IN_PROGRESS,
    PipelineStage.AI_GAP_ANALYSIS,
    PipelineStage.UNDER_REVIEW,
    PipelineStage.REVIEW_COMPLETE,
]

STAGE_LABELS = {
    PipelineStage.NOT_STARTED: "Not Started",
    PipelineStage.IN_PROGRESS: "In Progress",
    PipelineStage.AI_GAP_ANALYSIS: "AI Gap Analysis",
    PipelineStage.UNDER_REVIEW: "Under Review",
    PipelineStage.REVIEW_COMPLETE: "Review Complete",
}


class GapAnalysisStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineRecord(BaseModel):
    """Stored under audits/{audit_id}/current/pipeline.json (see README-datastruct)."""
    org_id: str
    audit_id: str
    project_id: str
    ai_system_id: str
    org_name: str = ""
    ai_system_name: str = ""
    stage: PipelineStage = PipelineStage.NOT_STARTED
    assigned_manager: Optional[str] = None
    assigned_practitioner: Optional[str] = None
    manager_name: Optional[str] = None
    practitioner_name: Optional[str] = None
    total_questions: int = 0
    answered_questions: int = 0
    gap_analysis_status: Optional[GapAnalysisStatus] = None
    gap_analysis_progress: int = 0  # 0-100
    gap_analysis_total: int = 0
    gap_analysis_completed: int = 0
    gap_analysis_task_id: Optional[str] = None
    submitted_at: Optional[str] = None
    gap_analysis_started_at: Optional[str] = None
    gap_analysis_completed_at: Optional[str] = None
    review_started_at: Optional[str] = None
    review_completed_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


class SubmitAssessmentBody(BaseModel):
    org_id: str
    project_id: str
    ai_system_id: str
    audit_id: str


class PipelineBoardResponse(BaseModel):
    stages: Dict[str, str] = Field(default_factory=lambda: {s.value: STAGE_LABELS[s] for s in STAGE_ORDER})
    stage_order: List[str] = Field(default_factory=lambda: [s.value for s in STAGE_ORDER])
    items: List[Dict] = Field(default_factory=list)
    total: int = 0
