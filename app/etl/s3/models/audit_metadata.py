# models/audit_metadata.py

from pydantic import BaseModel
from typing import Optional, Literal


class AuditMetadataModel(BaseModel):
    audit_id: str
    org_id: str

    auditor_id: str

    status: Literal["in_progress", "completed", "paused"]
    current_round: int

    started_at: str
    last_updated_at: str
    completed_at: Optional[str]