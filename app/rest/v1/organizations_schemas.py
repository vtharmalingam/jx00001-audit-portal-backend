"""REST request/response models for §3 Organizations (audit portal contract)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict


class PersonRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = ""
    name: str = ""
    email: Optional[str] = None
    role: Optional[str] = None


class ProjectCreateBody(BaseModel):
    project_id: Optional[str] = None
    project_name: str


class AuditCreateBody(BaseModel):
    project_id: str
    ai_system_id: str
    auditor_id: Optional[str] = None
    audit_id: Optional[str] = None


class BlockchainExportBody(BaseModel):
    project_id: str
    ai_system_id: str


class AiSystemCreateBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_id: Optional[str] = None
    system_id: Optional[str] = None
    name: Optional[str] = None
    description: str = ""
    manager: Optional[PersonRef] = None
    practitioner: Optional[PersonRef] = None
    auditor: Optional[PersonRef] = None
    status: Optional[str] = None
    stage: Optional[str] = None
    aict_approved: Optional[bool] = None
    added_at: Optional[str] = None


class OnboardingDecisionBody(BaseModel):
    decision: Literal["approve", "reject"]
    email: Optional[str] = None
    reason: Optional[str] = None


class OrgUpsertBody(BaseModel):
    """PATCH/PUT merge; all optional — empty patch is a no-op merge of timestamps only."""

    model_config = ConfigDict(extra="allow")

    domains: Optional[List[str]] = None
    org_type: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    stage: Optional[str] = None
    progress: Optional[Any] = None
    enrolled_at: Optional[str] = None
    aict_approved: Optional[bool] = None
    onboarded_by_type: Optional[str] = None
    onboarded_by_id: Optional[str] = None
    onboarded_by_name: Optional[str] = None
    archived: Optional[bool] = None
    is_diy: Optional[bool] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    address: Optional[str] = None
    referral_source: Optional[str] = None
    referral_code: Optional[str] = None
    payment_status: Optional[str] = None
    subscription_tier: Optional[str] = None
    manager: Optional[PersonRef] = None
    practitioner: Optional[PersonRef] = None
    auditor: Optional[PersonRef] = None
    manager_id: Optional[str] = None
    manager_name: Optional[str] = None
    manager_email: Optional[str] = None
    manager_role: Optional[str] = None
    practitioner_id: Optional[str] = None
    practitioner_name: Optional[str] = None
    practitioner_email: Optional[str] = None
    practitioner_role: Optional[str] = None
    auditor_id: Optional[str] = None
    auditor_name: Optional[str] = None
    auditor_email: Optional[str] = None
    auditor_role: Optional[str] = None


def org_upsert_to_patch(body: OrgUpsertBody) -> Dict[str, Any]:
    d = body.model_dump(exclude_none=True)
    for key in ("manager", "practitioner", "auditor"):
        ref = d.pop(key, None)
        if isinstance(ref, dict):
            prefix = key
            if ref.get("id") is not None:
                d[f"{prefix}_id"] = ref.get("id")
            if ref.get("name") is not None:
                d[f"{prefix}_name"] = ref.get("name")
            if ref.get("email") is not None:
                d[f"{prefix}_email"] = ref.get("email")
            if ref.get("role") is not None:
                d[f"{prefix}_role"] = ref.get("role")
    return d


def ai_system_create_to_dict(body: AiSystemCreateBody) -> Dict[str, Any]:
    out = body.model_dump(exclude_none=True)
    for key in ("manager", "practitioner", "auditor"):
        ref = out.get(key)
        if isinstance(ref, dict):
            out[key] = ref
    return out
