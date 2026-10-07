"""MKA fork seam C: the attribute scope rules as pure vectors (no database). Spec 2026-10-07 section 3.C."""

import pytest

from src.services.mka import compliance as svc
from src.services.mka import compliance_scope as cs


def eff(**kw):
    base = {"status": "matched", "is_officeholder": True, "level": None, "department": None, "role": None,
            "majlis": None, "region": None}
    base.update(kw)
    return base


VECTORS = [
    # (name, effective attributes, expected filter)
    ("mohtamim", eff(level="national", role="mohtamim", department="tabligh"), ("department", "tabligh")),
    ("naib mohtamim", eff(level="national", role="naib_mohtamim", department="maal"), ("department", "maal")),
    ("regional qaid", eff(level="regional", role="regional_qaid", region="Northeast"), ("region", "Northeast")),
    ("regional naib qaid", eff(level="regional", role="naib_qaid", region="Southwest"), ("region", "Southwest")),
    ("regional naib (alt spelling)", eff(level="regional", role="regional_naib_qaid", region="Gulf"), ("region", "Gulf")),
    ("majlis qaid", eff(level="local", role="qaid", majlis="Albany", region="Northeast"), ("majlis", "Albany")),
    ("majlis naib qaid", eff(level="local", role="naib_qaid", majlis="Albany", region="Northeast"), ("majlis", "Albany")),
    ("value is trimmed", eff(level="local", role="qaid", majlis="  Albany "), ("majlis", "Albany")),
    # everyone else gets nothing from this rule
    ("local sadr", eff(level="local", role="sadr", majlis="Albany"), None),
    ("regional nazim of a department", eff(level="regional", role="regional_nazim_dept", department="maal", region="Gulf"), None),
    ("local nazim", eff(level="local", role="nazim_dept", department="maal", majlis="Albany"), None),
    ("local mohtamim role at a Majlis", eff(level="local", role="mohtamim", department="maal", majlis="Albany"), None),
    ("national qaid", eff(level="national", role="qaid", majlis="Albany"), None),
    ("regional qaid without a region", eff(level="regional", role="regional_qaid"), None),
    ("majlis qaid without a Majlis", eff(level="local", role="qaid", region="Northeast"), None),
    ("mohtamim without a department", eff(level="national", role="mohtamim"), None),
    ("blank value", eff(level="local", role="qaid", majlis="   "), None),
    ("partial status", eff(status="partial", level="local", role="qaid", majlis="Albany"), None),
    ("ambiguous status", eff(status="ambiguous", level="regional", role="regional_qaid", region="Gulf"), None),
    ("unrecognized", eff(status="unrecognized"), None),
    ("empty", {}, None),
]


@pytest.mark.parametrize("name,effective,expected", VECTORS, ids=[v[0] for v in VECTORS])
def test_attribute_filter_vectors(name, effective, expected):
    assert cs.attributes_filter(effective) == expected


def test_all_rules_win_over_filter_rules_and_are_unchanged():
    national_aitmad_mohtamim = eff(level="national", role="mohtamim", department="aitmad")
    assert cs.attributes_grant_all(national_aitmad_mohtamim)  # still `all`; the router checks `all` first
    assert not cs.attributes_grant_all(eff(level="national", role="mohtamim", department="tabligh"))
    assert not cs.attributes_grant_all(eff(level="local", role="qaid", majlis="Albany"))


def scope(field=None, value=None, kind="filtered"):
    return cs.Scope(kind, 1, "attribute_filter", 5, filter_field=field, filter_value=value)


def test_filtered_scope_reports_the_filter_and_a_legacy_scope_that_is_never_all():
    s = scope("majlis", "Albany")
    assert s.roster_filter == {"majlis": "Albany"}
    assert s.legacy_scope() == "own" and s.kind == "filtered"
    assert s.filter_view() == {"field": "majlis", "value": "Albany", "majlis": "Albany", "label": "Your Majlis: Albany"}
    assert scope("department", "tabligh").filter_view()["label"] == "Your department: tabligh"
    assert scope("region", "Northeast").filter_view()["label"] == "Your region: Northeast"
    for kind in ("all", "own", "none"):
        plain = cs.Scope(kind, 1, "x")
        assert plain.roster_filter is None and plain.filter_view() is None and plain.legacy_scope() == kind


def test_a_half_built_filter_matches_nothing_never_everything():
    broken = scope("majlis", "")
    assert broken.roster_filter == {"majlis": ""} and broken.filter_view()["value"] == ""  # never mistaken for 'whole roster' ...
    assert scope(None, None).roster_filter == {"": ""}
    assert svc.roster_filter_clauses({"majlis": ""}) != []  # ... and a blank value matches nothing in SQL
    assert svc.roster_filter_clauses({"nonsense": "x"}) != []
    assert svc.roster_filter_clauses(None) == []


class Link:
    def __init__(self, kind, department, course_id=1):
        self.kind, self.department, self.course_id = kind, department, course_id


def test_a_department_filtered_viewer_sees_the_general_course_and_their_own_department_only():
    s = scope("department", "Tabligh")
    assert s.allows_link(Link("general", None))
    assert s.allows_link(Link("department", "tabligh"))
    assert not s.allows_link(Link("department", "maal"))
    region = scope("region", "Northeast")
    assert region.allows_link(Link("department", "maal")) and region.allows_link(Link("general", None))
    assert not cs.Scope("none", 1, "none").allows_link(Link("general", None))
