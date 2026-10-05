"""MKA fork: audience sections never reach an AI model for a learner who cannot see them (audience_strip + the ai.py hook)."""

import copy
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.db.organization_config import OrganizationConfig
from src.db.resource_authors import ResourceAuthor, ResourceAuthorshipEnum, ResourceAuthorshipStatusEnum
from src.db.users import SuperadminAPITokenUser, User
from src.services.ai import ai as ai_service
from src.services.ai.schemas.ai import SendActivityAIChatMessage, StartActivityAIChatSession
from src.services.mka import audience_strip
from src.services.mka.audience_strip import mka_content_for_ai
from src.tests.routers.mka_compliance_world import add_attributes, add_user

RATE_LIMIT_PATH = "src.services.security.rate_limiting.enforce_ai_rate_limit"
LOCAL = {"v": 1, "mode": "show", "groups": [{"level": ["local"], "department": ["tabligh"]}]}
NOT_NATIONAL = {"v": 1, "mode": "hide", "groups": [{"level": ["national"]}]}
NATIONAL = {"v": 1, "mode": "show", "groups": [{"level": ["national"]}]}


def para(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def aud(rule, *children, **attrs):
    return {"type": "mkaAudience", "attrs": {"id": "a1", "rule": rule, **attrs}, "content": list(children)}


def doc(*nodes):
    return {"type": "doc", "content": list(nodes)}


def texts(node):
    out = []
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, dict):
            if "text" in n:
                out.append(n["text"])
            stack.extend(n.values())
        elif isinstance(n, list):
            stack.extend(n)
    return sorted(out)


CONTENT = doc(
    para("PUBLIC"),
    aud(LOCAL, para("SECRET-LOCAL-TABLIGH")),
    aud(NOT_NATIONAL, para("HIDDEN-FROM-NATIONAL")),
    aud(NATIONAL, para("SECRET-NATIONAL")),
    para("PUBLIC-END"),
)


@pytest.fixture
async def people(db, org, other_org, admin_user, regular_user, course):
    await add_user(db, org.id, 10, "local.tabligh@example.invalid")
    await add_attributes(db, 10, "local.tabligh@example.invalid", level="local", department="tabligh", role="nazim_dept", majlis="Albany", region="Northeast")
    await add_user(db, org.id, 11, "national@example.invalid")
    await add_attributes(db, 11, "national@example.invalid", level="national", department="tabligh", role="mohtamim")
    await add_user(db, org.id, 12, "author@example.invalid")      # active creator of THIS course, no attributes
    await add_user(db, org.id, 13, "other.author@example.invalid")  # active creator of ANOTHER course
    await add_user(db, org.id, 14, "super@example.invalid")
    sup = await db.get(User, 14)
    sup.is_superadmin = True
    db.add(sup)
    now = str(datetime.now())
    for uid, uuid in ((12, "course_test"), (13, "course_elsewhere")):
        db.add(ResourceAuthor(resource_uuid=uuid, user_id=uid, authorship=ResourceAuthorshipEnum.CREATOR,
                              authorship_status=ResourceAuthorshipStatusEnum.ACTIVE, creation_date=now, update_date=now))
    await db.commit()
    return SimpleNamespace(course=SimpleNamespace(course_uuid="course_test"))


def as_user(uid):
    return SimpleNamespace(id=uid)


async def strip(db, uid, content=CONTENT, request=None, course=True, people=None):
    return await mka_content_for_ai(content, as_user(uid) if uid is not None else None, db, request,
                                    course=SimpleNamespace(course_uuid="course_test") if course else None)


# ---------------------------------------------------------------------------------------------------------
# unit
# ---------------------------------------------------------------------------------------------------------

async def test_local_tabligh_sees_matching_and_untargeted_sections_only(db, people, mock_request):
    got = await strip(db, 10, request=mock_request)
    assert texts(got) == sorted(["PUBLIC", "SECRET-LOCAL-TABLIGH", "HIDDEN-FROM-NATIONAL", "PUBLIC-END"])
    assert [n["type"] for n in got["content"]] == ["paragraph"] * 4  # matching sections are unwrapped: their paragraphs are top-level
    assert [texts(n)[0] for n in got["content"]] == ["PUBLIC", "SECRET-LOCAL-TABLIGH", "HIDDEN-FROM-NATIONAL", "PUBLIC-END"]


async def test_national_viewer_loses_local_and_hide_sections(db, people, mock_request):
    got = await strip(db, 11, request=mock_request)
    assert texts(got) == sorted(["PUBLIC", "SECRET-NATIONAL", "PUBLIC-END"])


async def test_unrecognized_viewer_sees_untargeted_and_hide_sections_never_show_sections(db, people, mock_request, regular_user):
    got = await strip(db, regular_user.id, request=mock_request)  # no attribute row
    assert texts(got) == sorted(["PUBLIC", "HIDDEN-FROM-NATIONAL", "PUBLIC-END"])


@pytest.mark.parametrize("user", [None, SimpleNamespace(id=0), SimpleNamespace(), SuperadminAPITokenUser()])
async def test_anonymous_and_token_principals_are_the_nobody_viewer(db, people, user):
    got = await mka_content_for_ai(CONTENT, user, db, None, course=SimpleNamespace(course_uuid="course_test"))
    assert texts(got) == sorted(["PUBLIC", "HIDDEN-FROM-NATIONAL", "PUBLIC-END"])  # hide-mode matches nobody-viewer; show never does


@pytest.mark.parametrize("uid", [1, 12, 14])  # org admin, active author of this course, superadmin
async def test_viewers_who_can_view_all_get_everything(db, people, mock_request, uid):
    got = await strip(db, uid, request=mock_request)
    assert [n["type"] for n in got["content"]] == ["paragraph"] * 5  # everything, unwrapped, in document order
    assert [texts(n)[0] for n in got["content"]] == ["PUBLIC", "SECRET-LOCAL-TABLIGH", "HIDDEN-FROM-NATIONAL", "SECRET-NATIONAL", "PUBLIC-END"]


async def test_admin_without_a_course_is_not_elevated_and_other_course_author_is_not_either(db, people, mock_request):
    assert "SECRET-NATIONAL" not in texts(await strip(db, 1, request=mock_request, course=False))
    got = await strip(db, 13, request=mock_request)  # author of a DIFFERENT course
    assert "SECRET-NATIONAL" not in texts(got) and "SECRET-LOCAL-TABLIGH" not in texts(got)


async def test_unknown_course_does_not_elevate(db, people, mock_request):
    got = await mka_content_for_ai(CONTENT, as_user(1), db, mock_request, course=SimpleNamespace(course_uuid="no_such_course"))
    assert "SECRET-NATIONAL" not in texts(got)


async def test_audience_sections_in_every_block_position_are_stripped(db, people, mock_request):
    content = doc(
        {"type": "blockquote", "content": [aud(NATIONAL, para("S-QUOTE")), para("ok-quote")]},
        {"type": "bulletList", "content": [{"type": "listItem", "content": [aud(NATIONAL, para("S-LIST")), para("ok-list")]}]},
        {"type": "calloutInfo", "content": [aud(NATIONAL, para("S-CALLOUT"))]},
        aud(LOCAL, para("ok-local"), aud(NATIONAL, para("S-NESTED"))),  # nested (the editor forbids it; a stored doc may still have it)
    )
    got = await strip(db, 10, content=content, request=mock_request)
    assert texts(got) == sorted(["ok-quote", "ok-list", "ok-local"])
    assert "mkaAudience" not in json.dumps(got)  # unwrapped inside quotes / lists too
    assert got["content"][0]["content"] == [para("ok-quote")] and got["content"][3] == para("ok-local")


async def test_malformed_audience_nodes_fail_closed(db, people, mock_request):
    content = doc(
        para("kept"),
        {"type": "mkaAudience", "content": [para("S-NO-ATTRS")]},
        {"type": "mkaAudience", "attrs": None, "content": [para("S-NULL-ATTRS")]},
        {"type": "mkaAudience", "attrs": {"rule": "not json"}, "content": [para("S-STRING-RULE")]},
        {"type": "mkaAudience", "attrs": {"rule": {"v": 1, "mode": "show", "groups": []}}, "content": [para("S-BAD-RULE")]},
        {"type": "mkaAudience", "attrs": {"rule": {"v": 2, "mode": "hide", "groups": [{}]}}, "content": [para("S-NEWER-VERSION")]},
        {"type": "mkaAudience", "attrs": {"rule": LOCAL}, "content": None},
        {"type": "mkaAudience", "attrs": {"rule": LOCAL}},
        5, None, "text", [para("odd-list")],
    )
    got = await strip(db, 10, content=content, request=mock_request)
    leftover = texts(got)
    assert "kept" in leftover and not any(t.startswith("S-") for t in leftover)


async def test_unwrap_is_recursive_and_keeps_order(db, people, mock_request):
    content = doc(para("a"), aud(LOCAL, para("b"), aud(LOCAL, para("c"), aud(NATIONAL, para("S"))), para("d")), para("e"))
    got = await strip(db, 10, content=content, request=mock_request)
    assert [texts(n)[0] for n in got["content"]] == ["a", "b", "c", "d", "e"]
    assert all(n["type"] == "paragraph" for n in got["content"])


async def test_audience_node_outside_a_list_is_emptied(db, people, mock_request):
    got = await strip(db, 11, content=aud(LOCAL, para("S-ROOT")), request=mock_request)
    assert got == {"type": "mkaAudience", "content": []}


async def test_input_is_never_mutated_and_output_is_independent(db, people, mock_request):
    before = copy.deepcopy(CONTENT)
    got = await strip(db, 11, request=mock_request)
    assert CONTENT == before
    got["content"][0]["content"][0]["text"] = "CHANGED"
    assert CONTENT == before
    full = await strip(db, 1, request=mock_request)
    full["content"][1]["content"].clear()
    assert CONTENT == before


async def test_documents_without_audience_sections_need_no_database(db):
    plain = doc(para("a"), {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "h"}]})
    got = await mka_content_for_ai(plain, as_user(7), None, None)  # no session: any query would raise
    assert got == plain and got is not plain
    for scalar in (None, "x", 3, [], {}):
        assert await mka_content_for_ai(scalar, None, None) == scalar


async def test_any_exception_strips_every_audience_section(db, people, mock_request):
    with patch.object(audience_strip, "_viewer", new=AsyncMock(side_effect=RuntimeError("db down"))):
        got = await strip(db, 1, request=mock_request)  # even an admin: the failure is not a license
    assert texts(got) == sorted(["PUBLIC", "PUBLIC-END"])
    with patch.object(audience_strip, "evaluate_rule", side_effect=ValueError("boom")):
        got = await strip(db, 10, request=mock_request)
    assert texts(got) == sorted(["PUBLIC", "PUBLIC-END"])
    with patch.object(audience_strip.audience_svc, "course_view_all", new=AsyncMock(side_effect=RuntimeError("x"))):
        assert texts(await strip(db, 1, request=mock_request)) == sorted(["PUBLIC", "PUBLIC-END"])


async def test_pathologically_deep_documents_fail_closed_to_an_empty_document(db, people, mock_request):
    node = para("S-DEEP")
    for _ in range(500):
        node = {"type": "blockquote", "content": [node]}
    deep = doc(aud(LOCAL, para("S-DEEP-AUD")), node)
    got = await strip(db, 10, content=deep, request=mock_request)
    assert got == {"type": "doc", "content": []}
    assert "S-DEEP" not in json.dumps(got)


# ---------------------------------------------------------------------------------------------------------
# the ai.py hook (all four entry points funnel through three call sites)
# ---------------------------------------------------------------------------------------------------------

@pytest.fixture
async def org_config(db, org):
    cfg = OrganizationConfig(org_id=org.id, config={"config_version": "1.0"})
    db.add(cfg)
    await db.commit()
    return cfg


@pytest.fixture
async def activity_with_audience(db, activity):
    activity.content = copy.deepcopy(CONTENT)
    db.add(activity)
    await db.commit()
    return activity


def as_user_with_membership(uid):
    from src.db.users import PublicUser

    return PublicUser(id=uid, username=f"u{uid}", first_name="F", last_name="L", email=f"u{uid}@x.invalid", user_uuid=f"user_{uid}")


def _patches(seen, asked):
    real = ai_service.structure_activity_content_by_type

    def spy(content):
        seen.append(copy.deepcopy(content))
        return real(content)

    async def fake_ask(question, history, text, system, model):
        asked.append(text)
        return {"output": "ok"}

    return [
        patch.object(ai_service, "check_resource_access", new_callable=AsyncMock),
        patch(RATE_LIMIT_PATH),
        patch.object(ai_service, "reserve_ai_credit", new_callable=AsyncMock),
        patch.object(ai_service, "structure_activity_content_by_type", side_effect=spy),
        patch.object(ai_service, "model_for_tier", return_value="test-model"),
        patch.object(ai_service, "get_chat_session_history", return_value={"aichat_uuid": "chat_1", "message_history": []}),
        patch.object(ai_service, "ask_ai", side_effect=fake_ask),
        patch.object(ai_service, "save_message_to_history"),
    ]


class _Ctx:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.start()

    def __exit__(self, *a):
        for p in reversed(self.patches):
            p.stop()


async def test_learner_prompt_content_excludes_hidden_sections_on_all_chat_paths(db, org, course, activity_with_audience, org_config, mock_request, regular_user, people):
    seen, asked = [], []
    with _Ctx(_patches(seen, asked)):
        await ai_service.ai_start_activity_chat_session(
            mock_request, StartActivityAIChatSession(activity_uuid="activity_test", message="hi"), regular_user, db)
        await ai_service.ai_send_activity_chat_message(
            mock_request, SendActivityAIChatMessage(aichat_uuid="chat_1", activity_uuid="activity_test", message="more"), regular_user, db)
        await ai_service._get_activity_and_course_info("activity_test", db, mock_request, regular_user)  # both streaming paths
    assert len(seen) == 3
    for content in seen:
        assert "SECRET-LOCAL-TABLIGH" not in json.dumps(content) and "SECRET-NATIONAL" not in json.dumps(content)
        assert "PUBLIC" in json.dumps(content)
    assert all("SECRET" not in (t or "") for t in asked)


async def test_learner_prompt_contains_the_text_of_sections_that_match_them(db, org, course, activity_with_audience, org_config, mock_request, people):
    """The model sees what the learner sees: a matching section is unwrapped, so the serializer (top-level blocks only) reads it."""
    seen, asked = [], []
    with _Ctx(_patches(seen, asked)):
        await ai_service.ai_start_activity_chat_session(
            mock_request, StartActivityAIChatSession(activity_uuid="activity_test", message="hi"), as_user_with_membership(10), db)
    top = [n["type"] for n in seen[0]["content"]]
    assert top == ["paragraph"] * 4                                # no wrapper left
    flat = json.dumps(seen[0])
    assert "SECRET-LOCAL-TABLIGH" in flat and "HIDDEN-FROM-NATIONAL" in flat and "SECRET-NATIONAL" not in flat
    prompt = asked[0] if isinstance(asked[0], str) else json.dumps(asked[0])
    assert "SECRET-LOCAL-TABLIGH" in prompt and "HIDDEN-FROM-NATIONAL" in prompt and "PUBLIC" in prompt
    assert "SECRET-NATIONAL" not in prompt


async def test_admin_prompt_content_keeps_every_section_unwrapped(db, org, course, activity_with_audience, org_config, mock_request, admin_user, people):
    seen, asked = [], []
    with _Ctx(_patches(seen, asked)):
        _a, _c, _o, _m, text = await ai_service._get_activity_and_course_info("activity_test", db, mock_request, admin_user)
    assert texts(seen[0]) == texts(CONTENT)
    assert [n["type"] for n in seen[0]["content"]] == ["paragraph"] * 5
    for needle in ("SECRET-LOCAL-TABLIGH", "HIDDEN-FROM-NATIONAL", "SECRET-NATIONAL"):
        assert needle in text
