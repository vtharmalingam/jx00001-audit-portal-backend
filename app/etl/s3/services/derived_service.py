"""
Rebuildable derived/ artifacts (README-datastruct §9).

Heavy work should run async (Celery); this module provides a small synchronous stub
and a task entrypoint so queues can call the same code path.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.etl.s3.utils.helpers import utc_now
from app.etl.s3.utils.s3_paths import derived_insights_key, derived_metrics_key, derived_risk_scores_key

logger = logging.getLogger(__name__)


class DerivedAuditService:
    def __init__(self, s3):
        self.s3 = s3

    def write_placeholder_bundle(
        self,
        org_id: str,
        audit_id: str,
        project_id: str,
        ai_system_id: str,
    ) -> Dict[str, Any]:
        """Idempotent placeholder objects until real metrics/LLM pipelines land."""
        now = utc_now()
        metrics: Dict[str, Any] = {
            "updated_at": now,
            "source": "derived_stub",
            "note": "Replace with real async recomputation (metrics, risk, insights).",
        }
        self.s3.write_json(
            derived_metrics_key(org_id, audit_id, project_id, ai_system_id),
            metrics,
        )
        self.s3.write_json(
            derived_risk_scores_key(org_id, audit_id, project_id, ai_system_id),
            {"updated_at": now, "overall_risk": "unknown", "categories": {}},
        )
        self.s3.write_json(
            derived_insights_key(org_id, audit_id, project_id, ai_system_id),
            {"updated_at": now, "summary": "", "top_issues": [], "recommendations": []},
        )
        return metrics


def schedule_derived_recompute(s3, org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> None:
    """Try Celery; on any failure run synchronous placeholder (safe for dev)."""
    try:
        from app.pipeline.tasks import recompute_derived_audit_task

        recompute_derived_audit_task.delay(org_id, audit_id, project_id, ai_system_id)
        return
    except Exception as e:
        logger.debug("derived async not scheduled (%s); using sync stub", e)
    try:
        DerivedAuditService(s3).write_placeholder_bundle(org_id, audit_id, project_id, ai_system_id)
    except Exception as e:
        logger.warning("derived stub write failed: %s", e)
