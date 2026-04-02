"""org_matches_filters — multi-value org_types (OR)."""

from app.etl.s3.services.org_normalize import org_matches_filters


def test_org_types_or_match():
    firm = {"org_id": "1", "onboarded_by_type": "firm", "name": "A"}
    client = {"org_id": "2", "onboarded_by_type": "firm_client", "name": "B"}
    other = {"org_id": "3", "onboarded_by_type": "aict", "name": "C"}

    assert org_matches_filters(firm, org_types=["firm", "firm_client"])
    assert org_matches_filters(client, org_types=["firm", "firm_client"])
    assert not org_matches_filters(other, org_types=["firm", "firm_client"])


def test_org_types_normalizes_aict_client():
    org = {"org_id": "x", "onboarded_by_type": "aict-client"}
    assert org_matches_filters(org, org_types=["aict"])
    assert org_matches_filters(org, org_types=["aict-client"])


def test_org_types_overrides_single_org_type_when_both_provided():
    org = {"org_id": "1", "onboarded_by_type": "firm_client"}
    # org_type=firm alone would exclude; org_types includes firm_client
    assert org_matches_filters(
        org,
        org_type="firm",
        org_types=["firm_client"],
    )


def test_single_org_type_unchanged_when_org_types_none():
    org = {"org_id": "1", "onboarded_by_type": "firm"}
    assert org_matches_filters(org, org_type="firm")
    assert not org_matches_filters(org, org_type="firm_client")
