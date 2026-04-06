"""
Composite identifiers and ULID helpers (see app/etl/s3/README-datastruct.md).

* ``audit_id`` for S3 paths is always a 26-char Crockford ULID.
* ``system_key`` / ``audit_key`` are logical strings; parse with fixed positions only.
"""

from __future__ import annotations

import re
from typing import Tuple

from ulid import ULID as _ULID

# Crockford Base32 (ULID); excludes I, L, O, U
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def new_audit_ulid() -> str:
    """New time-ordered audit id for ``audits/{audit_id}/`` (uppercase)."""
    return str(_ULID()).upper()


def validate_ulid(value: str) -> str:
    s = value.strip().upper()
    if not _ULID_RE.match(s):
        raise ValueError(f"invalid ULID: {value!r}")
    return s


def validate_project_id(value: str) -> str:
    """Exactly three digits (e.g. ``001``). No legacy single-digit scope."""
    p = str(value).strip()
    if not (p.isdigit() and len(p) == 3):
        raise ValueError("project_id must be exactly 3 digits")
    return p


def validate_ai_system_id(value: str) -> str:
    """Exactly four digits (e.g. ``0001``). No legacy single-digit scope."""
    s = str(value).strip()
    if not (s.isdigit() and len(s) == 4):
        raise ValueError("ai_system_id must be exactly 4 digits")
    return s


def format_system_key(org_id: str, project_id: str, ai_system_id: str) -> str:
    """Logical ``{org_id}-{project_id}-{ai_system_id}`` (not an S3 path)."""
    oid = validate_ulid(org_id)
    p = str(project_id).strip()
    s = str(ai_system_id).strip()
    if not (p.isdigit() and len(p) == 3):
        raise ValueError("project_id must be exactly 3 digits")
    if not (s.isdigit() and len(s) == 4):
        raise ValueError("ai_system_id must be exactly 4 digits")
    return f"{oid}-{p}-{s}"


def parse_system_key(system_key: str) -> Tuple[str, str, str]:
    """Fixed-position parse; returns (org_id, project_id, ai_system_id)."""
    k = system_key.strip().upper()
    if len(k) != 35 or k[26] != "-" or k[30] != "-":
        raise ValueError("invalid system_key: expected 35 chars with hyphens at 26 and 30")
    org_id, project_id, ai_system_id = k[0:26], k[27:30], k[31:35]
    validate_ulid(org_id)
    if not (project_id.isdigit() and len(project_id) == 3):
        raise ValueError("invalid project_id segment in system_key")
    if not (ai_system_id.isdigit() and len(ai_system_id) == 4):
        raise ValueError("invalid ai_system_id segment in system_key")
    return org_id, project_id, ai_system_id


def parse_audit_key(audit_key: str) -> Tuple[str, str, str, str]:
    """Fixed-position parse; returns (org_id, project_id, ai_system_id, audit_id)."""
    k = audit_key.strip().upper()
    if len(k) != 62 or k[35] != "-":
        raise ValueError("invalid audit_key: expected 62 chars with hyphen at 35")
    system_key, audit_id = k[0:35], k[36:62]
    validate_ulid(audit_id)
    o, p, s = parse_system_key(system_key)
    return o, p, s, audit_id


def format_audit_key(org_id: str, project_id: str, ai_system_id: str, audit_id: str) -> str:
    """Logical composite for APIs/logging only (not an S3 prefix)."""
    sk = format_system_key(org_id, project_id, ai_system_id)
    aid = validate_ulid(audit_id)
    return f"{sk}-{aid}"
