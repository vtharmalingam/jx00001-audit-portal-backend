"""End-to-end S3 service flow tests (in-memory, no AWS calls)."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pytest

from app.etl.s3.services.ai_service import AIService
from app.etl.s3.services.answer_service import AnswerService
from app.etl.s3.services.audit_lifecycle_service import AuditLifecycleService
from app.etl.s3.services.auditor_service import AuditorService
from app.etl.s3.services.evidence_service import EvidenceService
from app.etl.s3.services.operational_service import OperationalService
from app.etl.s3.services.report_service import ReportService
from app.etl.s3.utils.s3_paths import (
    ai_analysis_index_key,
    ai_key,
    answers_index_key,
    audit_metadata_key,
    audit_summary_key,
    auditor_feedback_index_key,
    derived_metrics_key,
    domain_lookup_key,
    org_lookup_key,
)


class _FakeS3Client:
    def __init__(self, store: Dict[str, Any]):
        self._store = store

    def list_objects_v2(self, Bucket: str, Prefix: str = "", Delimiter: Optional[str] = None, ContinuationToken: Optional[str] = None):  # noqa: N803
        keys = sorted(k for k in self._store if k.startswith(Prefix))
        if Delimiter:
            prefixes = set()
            plen = len(Prefix)
            for k in keys:
                tail = k[plen:]
                if Delimiter in tail:
                    first = tail.split(Delimiter, 1)[0]
                    prefixes.add(Prefix + first + Delimiter)
            return {"CommonPrefixes": [{"Prefix": p} for p in sorted(prefixes)], "IsTruncated": False}
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}


class FakeS3:
    def __init__(self):
        self.bucket = "fake-bucket"
        self.store: Dict[str, Any] = {}
        self.client = _FakeS3Client(self.store)

    def read_json(self, key: str):
        value = self.store.get(key)
        if isinstance(value, dict) or isinstance(value, list):
            return value
        return None

    def write_json(self, key: str, data: Any):
        self.store[key] = data

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream"):
        self.store[key] = data

    def copy_object(self, src_key: str, dest_key: str):
        self.store[dest_key] = self.store[src_key]

    def delete_object(self, key: str):
        self.store.pop(key, None)


class MockLLM:
    def analyze(self, text: str) -> Dict[str, Any]:
        return {
            "risk_level": "medium",
            "confidence": 0.93,
            "gap_report": {
                "synthesized_summary": f"analysis:{text[:8]}",
                "key_themes": ["controls"],
                "user_gap": ["missing evidence"],
                "insights": ["needs references"],
                "match_score": 0.72,
            },
        }


def _run_lifecycle_flow(s3):
    # Crockford ULID org + ULID audit; 3-digit project + 4-digit system per README-datastruct.
    org_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    project_id = "001"
    ai_system_id = "0001"
    question_id = "Q1_1"

    # 1) Organization onboarding layer + lookup synchronization.
    ops = OperationalService(s3)
    profile = ops.merge_org_profile(
        org_id,
        {
            "name": "Acme",
            "org_type": "firm",
            "domains": ["acme.com"],
        },
    )
    assert profile["org_id"] == org_id
    assert s3.read_json(domain_lookup_key("acme.com")) == {"org_id": org_id}
    assert s3.read_json(org_lookup_key(org_id))["org_id"] == org_id

    # 2) Structural hierarchy: project and AI system.
    project = ops.create_project(org_id, "Fraud Platform", project_id=project_id)
    assert project["project_id"] == project_id

    system = ops.add_ai_system(
        org_id,
        {
            "project_id": project_id,
            "system_id": ai_system_id,
            "name": "Risk Model",
            "status": "in_progress",
        },
    )
    assert system["project_id"] == project_id
    assert system["system_id"] == ai_system_id
    audit_id = system["audit_id"]
    assert len(audit_id) == 26

    # 3) Audit control plane (metadata + summary + timeline) created in add_ai_system.
    lifecycle = AuditLifecycleService(s3)
    meta = lifecycle.get_metadata(org_id, audit_id, project_id, ai_system_id)
    assert meta is not None
    assert meta["audit_id"] == audit_id
    assert meta["project_id"] == project_id
    assert meta["ai_system_id"] == ai_system_id
    assert s3.read_json(audit_metadata_key(org_id, audit_id, project_id, ai_system_id))["status"] == "in_progress"

    # 4) Mutable current state: answer, evidence, AI analysis, auditor review.
    ans = AnswerService(s3).upsert_answer(
        org_id,
        audit_id,
        project_id,
        ai_system_id,
        question_id,
        "Initial answer",
        state="submitted",
        user="user@acme.com",
    )
    assert ans["version"] == 1
    ans_idx = s3.read_json(answers_index_key(org_id, audit_id, project_id, ai_system_id))
    assert ans_idx and len(ans_idx.get("items") or []) == 1
    assert ans_idx["items"][0]["question_id"] == question_id

    # Use override key so the test does not depend on binary upload bytes.
    ev = EvidenceService(s3).register_evidence(
        org_id,
        audit_id,
        question_id,
        file_name="policy.pdf",
        project_id=project_id,
        ai_system_id=ai_system_id,
        uploaded_by="user@acme.com",
        s3_key=f"organizations/{org_id}/external/policy.pdf",
    )
    assert ev["file_name"] == "policy.pdf"

    # AI processes only submitted answers and pins last_analyzed_version.
    ai_result = AIService(s3, MockLLM()).process_org(
        org_id,
        audit_id,
        project_id,
        ai_system_id,
        question_id=question_id,
    )
    assert ai_result["processed"] == 1
    assert s3.read_json(ai_key(org_id, audit_id, question_id, project_id, ai_system_id))["last_analyzed_version"] == 1

    # Auditor feedback links review to the exact answer version.
    review = AuditorService(s3).update_feedback(
        org_id,
        audit_id,
        question_id,
        {
            "version": 1,
            "auditor_id": "aud_1",
            "review_state": "needs_revision",
            "summary": "Need stronger evidence",
            "feedback": [],
            "recommendations": ["Add architecture diagram"],
        },
        project_id,
        ai_system_id,
    )
    assert review["review_state"] == "needs_revision"
    fb_idx = s3.read_json(auditor_feedback_index_key(org_id, audit_id, project_id, ai_system_id))
    assert fb_idx and any(i.get("question_id") == question_id for i in (fb_idx.get("items") or []))

    # 5) Read model: consolidated audit view for UI/reporting.
    view = ReportService(s3).get_full_audit_view(
        org_id,
        audit_id,
        project_id=project_id,
        ai_system_id=ai_system_id,
    )
    item = view["data"][question_id]
    assert item["attachments"][0]["file_name"] == "policy.pdf"
    assert item["review"]["review_state"] == "needs_revision"

    # 6) Derived metrics: summary reflects answered/AI/reviewed counts.
    summary = s3.read_json(audit_summary_key(org_id, audit_id, project_id, ai_system_id))
    assert summary["answered"] == 1
    assert summary["ai_processed"] == 1
    assert summary["reviewed"] == 1
    derived = s3.read_json(derived_metrics_key(org_id, audit_id, project_id, ai_system_id))
    assert derived and derived.get("source") == "derived_stub"


def test_org_project_ai_system_assessment_lifecycle_fake():
    """Fast deterministic check using in-memory S3."""
    _run_lifecycle_flow(FakeS3())


@pytest.mark.skipif(
    os.getenv("RUN_REAL_S3_LIFECYCLE") != "1",
    reason="Set RUN_REAL_S3_LIFECYCLE=1 to run against real S3 via real_s3 fixture.",
)
def test_org_project_ai_system_assessment_lifecycle_real_s3(real_s3):
    """Optional integration check against real S3 bucket fixture."""
    _run_lifecycle_flow(real_s3)
