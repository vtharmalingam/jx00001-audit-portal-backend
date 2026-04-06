"""Unit tests for audit path layout (no S3)."""

from app.etl.s3.utils import s3_paths


def test_audit_root_nested_scope():
    r = s3_paths.audit_root("o1", "a1", "001", "0001")
    assert "organizations/o1/projects/001/systems/0001/audits/a1" in r


def test_audit_root_non_zero_scope():
    r = s3_paths.audit_root("o1", "a1", "proj1", "sys1")
    assert "organizations/o1/projects/proj1/systems/sys1/audits/a1" in r


def test_answer_key_scope_variants():
    k0 = s3_paths.answer_key("o", "1", "Q1", "001", "0001")
    assert "/projects/001/systems/0001/audits/1/current/answers/Q1.json" in k0
    kv = s3_paths.answer_key("o", "1", "Q1", "p", "s")
    assert "/projects/p/systems/s/audits/1/current/answers/Q1.json" in kv


def test_derived_prefix_under_audit():
    aid = "01J7RZ8G6E9VX4D3N2C5M8P1QR"
    d = s3_paths.derived_prefix("o", aid, "001", "0001")
    assert f"/systems/0001/audits/{aid}/derived" in d
