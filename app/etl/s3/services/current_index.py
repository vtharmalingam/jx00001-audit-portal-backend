"""
Maintain current/{section}/_index.json alongside per-question JSON (README-datastruct §8.2).
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.etl.s3.utils.helpers import utc_now
from app.etl.s3.utils.s3_paths import (
    ai_analysis_index_key,
    answers_index_key,
    auditor_feedback_index_key,
)


def _normalize_items(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    items = raw.get("items")
    if not isinstance(items, list):
        return []
    return [i for i in items if isinstance(i, dict)]


def _upsert_sorted(items: List[Dict[str, Any]], question_id: str, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    rest = [i for i in items if i.get("question_id") != question_id]
    rest.append(entry)
    return sorted(rest, key=lambda x: str(x.get("question_id") or ""))


def sync_answers_index(
    s3,
    org_id: str,
    audit_id: str,
    *,
    question_id: str,
    version: int,
    state: str,
    project_id: str,
    ai_system_id: str,
) -> None:
    key = answers_index_key(org_id, audit_id, project_id, ai_system_id)
    now = utc_now()
    items = _upsert_sorted(
        _normalize_items(s3.read_json(key)),
        question_id,
        {
            "question_id": question_id,
            "version": int(version),
            "last_updated": now,
            "state": state,
        },
    )
    s3.write_json(key, {"items": items, "last_updated": now})


def sync_ai_analysis_index(
    s3,
    org_id: str,
    audit_id: str,
    *,
    question_id: str,
    last_analyzed_version: int,
    project_id: str,
    ai_system_id: str,
) -> None:
    key = ai_analysis_index_key(org_id, audit_id, project_id, ai_system_id)
    now = utc_now()
    items = _upsert_sorted(
        _normalize_items(s3.read_json(key)),
        question_id,
        {
            "question_id": question_id,
            "version": int(last_analyzed_version),
            "last_updated": now,
            "state": "completed",
        },
    )
    s3.write_json(key, {"items": items, "last_updated": now})


def sync_auditor_feedback_index(
    s3,
    org_id: str,
    audit_id: str,
    *,
    question_id: str,
    reviewed_version: int,
    review_state: str,
    project_id: str,
    ai_system_id: str,
) -> None:
    key = auditor_feedback_index_key(org_id, audit_id, project_id, ai_system_id)
    now = utc_now()
    items = _upsert_sorted(
        _normalize_items(s3.read_json(key)),
        question_id,
        {
            "question_id": question_id,
            "version": int(reviewed_version),
            "last_updated": now,
            "state": str(review_state or ""),
        },
    )
    s3.write_json(key, {"items": items, "last_updated": now})
