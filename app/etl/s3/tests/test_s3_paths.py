"""Unit tests for audit path layout (v2-only, no S3)."""

from app.etl.s3.utils import s3_paths


def test_audit_root_defaults_to_nested_zero_scope():
    r = s3_paths.audit_root("o1", "a1", "0", "0")
    assert "organizations/o1/projects/0/ai_systems/0/audits/a1" in r


def test_v2_audit_root_non_zero_scope():
    r = s3_paths.audit_root("o1", "a1", "proj1", "sys1")
    assert "organizations/o1/projects/proj1/ai_systems/sys1/audits/a1" in r


def test_answer_key_v2_scope_variants():
    k0 = s3_paths.answer_key("o", "1", "Q1", "0", "0")
    assert "/projects/0/ai_systems/0/audits/1/current/answers/Q1.json" in k0
    kv = s3_paths.answer_key("o", "1", "Q1", "p", "s")
    assert "/projects/p/ai_systems/s/audits/1/current/answers/Q1.json" in kv
