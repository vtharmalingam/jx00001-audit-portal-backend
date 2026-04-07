"""
Purpose: Pure shaping / rules — map stored org_profile to the REST Org contract, list
filter matching (org_type / org_types, archived, search, etc.), and pagination helpers
(no S3 I/O).

Normalize stored org_profile JSON toward the audit-portal ``Org`` contract.

Nested ``manager`` / ``practitioner`` / ``auditor`` are ``PersonRef`` shapes when flat
``{role}_id`` / ``{role}_name`` / ``{role}_email`` / ``{role}_role`` exist or nested dict.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def _normalize_onboarded_channel(value: str) -> str:
    """Lowercase and map aict-client → aict (same as single-value org_type filter)."""
    return str(value).strip().lower().replace("aict-client", "aict")


def _org_channel_key(org: Dict[str, Any]) -> str:
    ch = org.get("onboarded_by_type") or ""
    return _normalize_onboarded_channel(ch) if ch else ""


def _person(role: str, src: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    nested = src.get(role)
    if isinstance(nested, dict) and any(
        nested.get(k) for k in ("id", "name", "email", "role")
    ):
        return {
            "id": str(nested.get("id") or ""),
            "name": str(nested.get("name") or ""),
            "email": nested.get("email"),
            "role": nested.get("role"),
        }

    rid = src.get(f"{role}_id")
    name = src.get(f"{role}_name")
    email = src.get(f"{role}_email")
    rrole = src.get(f"{role}_role")

    if not any([rid, name, email, rrole]):
        return None

    return {
        "id": str(rid or ""),
        "name": str(name or ""),
        "email": email,
        "role": rrole,
    }


def normalize_org(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Merge defaults + nested PersonRefs for REST org payloads."""
    if not profile:
        profile = {}

    org_id = profile.get("org_id") or ""

    base: Dict[str, Any] = {
        "org_id": org_id,
        "name": profile.get("name"),
        "email": profile.get("email"),
        "status": profile.get("status", "pending"),
        "stage": profile.get("stage"),
        "progress": profile.get("progress"),
        "enrolled_at": profile.get("enrolled_at"),
        "aict_approved": profile.get("aict_approved"),
        "onboarded_by_type": profile.get("onboarded_by_type")
        or profile.get("org_type")
        or profile.get("org_channel"),
        "onboarded_by_id": profile.get("onboarded_by_id"),
        "onboarded_by_name": profile.get("onboarded_by_name"),
        "archived": profile.get("archived", False),
        "is_diy": profile.get("is_diy"),
        "contact_name": profile.get("contact_name"),
        "phone": profile.get("phone"),
        "website": profile.get("website"),
        "industry": profile.get("industry"),
        "address": profile.get("address"),
        "referral_source": profile.get("referral_source"),
        "referral_code": profile.get("referral_code"),
        "payment_status": profile.get("payment_status"),
        "subscription_tier": profile.get("subscription_tier"),
        "created_at": profile.get("created_at"),
        "updated_at": profile.get("updated_at"),
    }

    for role in ("manager", "practitioner", "auditor"):
        p = _person(role, profile)
        if p:
            base[f"{role}_id"] = profile.get(f"{role}_id") or p.get("id")
            base[f"{role}_name"] = profile.get(f"{role}_name") or p.get("name")
            base[f"{role}_email"] = profile.get(f"{role}_email") or p.get("email")
            base[f"{role}_role"] = profile.get(f"{role}_role") or p.get("role")
            base[role] = p
        else:
            base[role] = profile.get(role)

    reserved = set(base.keys())
    for k, v in profile.items():
        if k not in reserved:
            base[k] = v

    return base


def org_matches_filters(
    org: Dict[str, Any],
    *,
    onboarded_by: Optional[str] = None,
    onboarded_by_id: Optional[str] = None,
    org_type: Optional[str] = None,
    org_types: Optional[Sequence[str]] = None,
    aict_approved: Optional[bool] = None,
    stage: Optional[str] = None,
    status: Optional[str] = None,
    archived: Optional[bool] = None,
    q: Optional[str] = None,
    manager_id: Optional[str] = None,
    practitioner_id: Optional[str] = None,
) -> bool:
    wants: Optional[set[str]] = None
    if org_types is not None:
        wants = {
            _normalize_onboarded_channel(x)
            for x in org_types
            if x is not None and str(x).strip()
        }
    if wants:
        if _org_channel_key(org) not in wants:
            return False
    else:
        channel_filter = onboarded_by or org_type
        if channel_filter:
            if _org_channel_key(org) != _normalize_onboarded_channel(channel_filter):
                return False

    if onboarded_by_id and (org.get("onboarded_by_id") or "") != onboarded_by_id:
        return False

    if aict_approved is not None:
        if bool(org.get("aict_approved")) != aict_approved:
            return False

    if stage and (org.get("stage") or "") != stage:
        return False
    if status and (org.get("status") or "") != status:
        return False
    if archived is not None and bool(org.get("archived")) != archived:
        return False

    if q:
        ql = q.lower()
        blob = " ".join(
            str(x)
            for x in (
                org.get("org_id"),
                org.get("name"),
                org.get("email"),
            )
            if x
        ).lower()
        if ql not in blob:
            return False

    if manager_id and (org.get("manager_id") or "") != manager_id:
        return False
    if practitioner_id and (org.get("practitioner_id") or "") != practitioner_id:
        return False

    return True


def paginate(items: List[Dict], page: int, page_size: int) -> tuple[List[Dict], int]:
    page = max(1, page)
    page_size = max(1, min(page_size, 500))
    total = len(items)
    start = (page - 1) * page_size
    return items[start : start + page_size], total
