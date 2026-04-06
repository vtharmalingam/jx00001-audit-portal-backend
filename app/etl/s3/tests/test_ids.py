"""Composite id parsing (fixed-position)."""

import pytest

from app.etl.s3.utils.ids import (
    format_audit_key,
    format_system_key,
    parse_audit_key,
    parse_system_key,
    validate_ulid,
)


def test_parse_system_key_ok():
    sk = "01ARZ3NDEKTSV4RRFFQ69G5FAV-001-0001"
    o, p, s = parse_system_key(sk.lower())
    assert o == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert p == "001"
    assert s == "0001"


def test_parse_system_key_bad_length():
    with pytest.raises(ValueError):
        parse_system_key("01ARZ3NDEKTSV4RRFFQ69G5FAV-001-01")


def test_parse_audit_key_ok():
    ak = "01ARZ3NDEKTSV4RRFFQ69G5FAV-001-0001-01J7RZ8G6E9VX4D3N2C5M8P1QR"
    o, p, s, aid = parse_audit_key(ak)
    assert o == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert p == "001"
    assert s == "0001"
    assert aid == "01J7RZ8G6E9VX4D3N2C5M8P1QR"


def test_format_roundtrip():
    sk = format_system_key("01ARZ3NDEKTSV4RRFFQ69G5FAV", "001", "0001")
    assert parse_system_key(sk) == ("01ARZ3NDEKTSV4RRFFQ69G5FAV", "001", "0001")
    ak = format_audit_key("01ARZ3NDEKTSV4RRFFQ69G5FAV", "001", "0001", "01J7RZ8G6E9VX4D3N2C5M8P1QR")
    assert parse_audit_key(ak) == ("01ARZ3NDEKTSV4RRFFQ69G5FAV", "001", "0001", "01J7RZ8G6E9VX4D3N2C5M8P1QR")


def test_validate_ulid_rejects_illegal_letters():
    with pytest.raises(ValueError):
        validate_ulid("O1ARZ3NDEKTSV4RRFFQ69G5FAV")  # O not in Crockford set
