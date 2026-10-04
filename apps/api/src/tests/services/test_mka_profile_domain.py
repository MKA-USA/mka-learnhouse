import pytest
from fastapi import HTTPException

from src.services.users.mka_profile import (
    MAJLIS_TO_REGION,
    MkaProfileIn,
    normalize_amc_id,
    normalize_mobile,
    options_payload,
    parse_profile,
    region_for,
)

EXPECTED_REGIONS = {
    "East", "Great Lakes", "Gulf", "Midwest", "Muqami", "New York Metro",
    "Northeast", "Northwest", "Southeast", "Southwest", "Virginia",
}


def test_mapping_has_52_majlis_and_11_regions():
    assert len(MAJLIS_TO_REGION) == 52
    assert set(MAJLIS_TO_REGION.values()) == EXPECTED_REGIONS


@pytest.mark.parametrize("majlis,region", [
    ("Baltimore", "East"), ("Detroit", "Great Lakes"), ("Fort Worth", "Gulf"),
    ("Zion", "Midwest"), ("Muqami", "Muqami"), ("Queens", "New York Metro"),
    ("Syracuse-Binghamton", "Northeast"), ("Silicon Valley", "Northwest"),
    ("Tennessee", "Southeast"), ("Las Vegas", "Southwest"), ("RTP", "Virginia"),
    ("North Virginia", "Virginia"),
])
def test_region_for_spot_checks(majlis, region):
    assert region_for(majlis) == region


@pytest.mark.parametrize("raw,expected", [
    ("(703) 234-0142", "+17032340142"),
    ("703.234.0142", "+17032340142"),
    ("+1 703 234 0142", "+17032340142"),
    ("1-703-234-0142", "+17032340142"),
    ("7032340142", "+17032340142"),
    ("", None),
    ("   ", None),
    (None, None),
])
def test_normalize_mobile_ok(raw, expected):
    assert normalize_mobile(raw) == expected


@pytest.mark.parametrize("raw", [
    "123", "0032340142", "1032340142", "703 034 0142", "+44 20 7946 0958",
    "703-234-014a", "70323401420",
])
def test_normalize_mobile_rejects(raw):
    with pytest.raises(ValueError):
        normalize_mobile(raw)


def test_normalize_mobile_rejects_non_string():
    with pytest.raises(ValueError):
        normalize_mobile(7032340142)


def test_normalize_mobile_rejects_unicode_digits():
    with pytest.raises(ValueError):
        normalize_mobile("703234٠١٤٢")


@pytest.mark.parametrize("raw,expected", [
    ("12345", "12345"), (" 00123 ", "00123"), ("", None), (None, None),
    ("1" * 15, "1" * 15),
])
def test_normalize_amc_ok(raw, expected):
    assert normalize_amc_id(raw) == expected


@pytest.mark.parametrize("raw", ["12a", "1 2", "-5", "1" * 16, "١٢٣"])
def test_normalize_amc_rejects(raw):
    with pytest.raises(ValueError):
        normalize_amc_id(raw)


def test_normalize_amc_rejects_non_string():
    with pytest.raises(ValueError):
        normalize_amc_id(12345)


def test_profile_in_derives_nothing_and_ignores_unknown_keys():
    p = MkaProfileIn.model_validate(
        {"majlis": "Baltimore", "region": "Midwest", "extra_metadata": {"x": 1}}
    )
    assert p.majlis == "Baltimore"
    assert "region" not in p.model_dump()
    assert "extra_metadata" not in p.model_dump()


def test_profile_in_tanzeem():
    assert MkaProfileIn(majlis="Zion", tanzeem="Khadim").tanzeem == "khadim"
    assert MkaProfileIn(majlis="Zion", tanzeem="").tanzeem is None
    with pytest.raises(ValueError):
        MkaProfileIn(majlis="Zion", tanzeem="both")


def test_profile_in_rejects_unknown_majlis():
    with pytest.raises(ValueError):
        MkaProfileIn(majlis="Atlantis")


def test_parse_profile_required_missing_is_422():
    with pytest.raises(HTTPException) as e:
        parse_profile(None, required=True)
    assert e.value.status_code == 422
    assert e.value.detail[0]["field"] == "majlis"


def test_parse_profile_optional_missing_is_none():
    assert parse_profile(None, required=False) is None


def test_parse_profile_field_errors_are_clean():
    with pytest.raises(HTTPException) as e:
        parse_profile({"majlis": "Zion", "amc_id": "12a"}, required=True)
    assert e.value.status_code == 422
    assert e.value.detail == [{"field": "amc_id", "message": "AMC ID must contain digits only"}]


def test_parse_profile_rejects_amc_id_as_number():
    with pytest.raises(HTTPException) as e:
        parse_profile({"majlis": "Zion", "amc_id": 12345}, required=True)
    assert e.value.status_code == 422
    assert e.value.detail == [{"field": "amc_id", "message": "AMC ID must contain digits only"}]


def test_parse_profile_rejects_mobile_as_number():
    with pytest.raises(HTTPException) as e:
        parse_profile({"majlis": "Zion", "mobile": 7032340142}, required=True)
    assert e.value.status_code == 422
    assert e.value.detail == [{"field": "mobile", "message": "Enter a valid US mobile number"}]


def test_options_payload_shape():
    o = options_payload()
    assert len(o["majlis"]) == 52
    assert o["majlis"][0] == {"name": "Albany", "region": "Northeast"}
    assert [t["value"] for t in o["tanzeem"]] == ["khadim", "tifl"]
