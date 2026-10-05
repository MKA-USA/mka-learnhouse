"""MKA fork: compliance read-model helpers (contact self-check shapes, scope rule, CSV cap)."""

from types import SimpleNamespace

from src.services.mka import compliance as svc
from src.services.mka import compliance_scope as scope
from src.tests.routers.mka_compliance_world import FORM_CONTENTS, quiz_contents


def task(tid, typ, contents):
    return SimpleNamespace(id=tid, assignment_type=typ, contents=contents)


def test_extract_contact_answers_from_the_stored_shapes():
    tasks = [task(1, "QUIZ", quiz_contents(["Albany", "Boston"])), task(2, "FORM", FORM_CONTENTS)]
    subs = {
        1: {"submissions": [{"questionUUID": "q-majlis", "optionUUID": "o-Albany", "answer": False},
                            {"questionUUID": "q-majlis", "optionUUID": "o-Boston", "answer": True}]},
        2: {"submissions": [{"questionUUID": "q-rq", "blankUUID": "b-rq", "answer": " Rob Qaid "},
                            {"questionUUID": "q-head", "blankUUID": "b-head", "answer": "Jane Doe"}]},
    }
    assert svc.extract_contact_answers(tasks, subs) == {"majlis": "Boston", "regional_qaid": "Rob Qaid", "dept_head": "Jane Doe"}


def test_extract_contact_answers_tolerates_garbage():
    tasks = [task(1, "QUIZ", None), task(2, "FORM", {"questions": ["x", {"questionText": None}]}), task(3, "FORM", FORM_CONTENTS)]
    assert svc.extract_contact_answers(tasks, {1: "bad", 2: {"submissions": "bad"}, 3: {"submissions": [None, 3]}}) == {
        "majlis": None, "regional_qaid": None, "dept_head": None}


def test_attribute_scope_rules_require_national_and_matched():
    ok = {"status": "matched", "level": "national", "department": "aitmad"}
    assert scope.attributes_grant_all(ok)
    assert scope.attributes_grant_all({"status": "matched", "level": "national", "role": "sadr"})
    assert not scope.attributes_grant_all({**ok, "level": "local"})
    assert not scope.attributes_grant_all({**ok, "status": "unrecognized"})
    assert not scope.attributes_grant_all({"status": "matched", "level": "local", "role": "sadr"})
    assert not scope.attributes_grant_all({})


def test_uuid_candidates_accept_bare_and_prefixed():
    assert scope.uuid_candidates("course_abc") == ["course_abc"]
    assert scope.uuid_candidates("abc") == ["abc", "course_abc"]


def test_csv_cap():
    assert svc.MAX_CSV_ROWS == 5000 and svc.MAX_PAGE_SIZE == 200
