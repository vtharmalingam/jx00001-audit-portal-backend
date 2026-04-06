"""Validate org/audit ULIDs and 3+4 digit project/system segments on audit-scoped APIs."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status


def enforce_strict_audit_scope(
    org_id: str,
    audit_id: Optional[str],
    *,
    project_id: str,
    ai_system_id: str,
    require_audit_id: bool = True,
) -> None:
    """Raise 400 unless identifiers match the v2 contract (no legacy ``0`` scope)."""
    from app.etl.s3.utils.ids import (
        validate_ai_system_id,
        validate_project_id,
        validate_ulid,
    )

    try:
        validate_ulid(org_id)
        validate_project_id(project_id)
        validate_ai_system_id(ai_system_id)
        aid = (audit_id or "").strip()
        if require_audit_id:
            if not aid:
                raise ValueError("audit_id is required")
            validate_ulid(aid)
        elif aid:
            validate_ulid(aid)
    except ValueError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_AUDIT_IDS", "message": str(e)},
        ) from e
