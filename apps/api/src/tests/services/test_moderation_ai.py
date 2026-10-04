"""AI moderation wiring: opt-in, scheduler, extraction, hook sites.

Phase 1 is advisory: flags are recorded for staff, nothing is blocked, hidden
or graded, and no content text is persisted.
"""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from config.config import JevConfig
from src.db.communities.communities import Community
from src.db.communities.discussions import Discussion, DiscussionUpdate
from src.db.communities.discussion_comments import DiscussionCommentUpdate
from src.db.courses.assignments import (
    Assignment,
    AssignmentTask,
    AssignmentTaskSubmission,
    AssignmentTaskTypeEnum,
    GradingTypeEnum,
)
from src.db.moderation_flags import ModerationFlag
from src.db.organization_config import AdminToggles, OrganizationConfig
from src.db.trails import Trail
from src.db.users import UserUpdate
from src.services.ai.jev.moderation import ModerationResult
from src.services.moderation_ai import scheduler, settings
from src.services.moderation_ai.extractors import (
    assignment_submission_text,
    forum_text,
    profile_text,
    task_text,
)

LONG = "My phone number is 555-0100 and you are all useless people, honestly."


def _jev_cfg(**kw):
    base = {"enabled": True, "api_key": "k", "allowed_org_ids": []}
    base.update(kw)
    return JevConfig(**base)


@pytest.fixture(autouse=True)
def _reset_state():
    scheduler._rate_seen.clear()
    scheduler._content_calls.clear()
    scheduler._scored.clear()
    scheduler._background_tasks.clear()
    scheduler._pending_trailing.clear()
    with patch("src.core.redis.get_redis_client", return_value=None):
        yield
    for t in list(scheduler._background_tasks):
        t.cancel()
    scheduler._background_tasks.clear()
    scheduler._pending_trailing.clear()


@pytest.fixture
def jev_on():
    with patch.object(settings, "get_learnhouse_config") as m:
        m.return_value.jev_config = _jev_cfg()
        yield


@pytest.fixture
def jev_off():
    with patch.object(settings, "get_learnhouse_config") as m:
        m.return_value.jev_config = None
        yield


async def _config(db, org, enabled=None, surfaces=None, version="2.0"):
    if version == "2.0":
        blob = {"config_version": "2.0"}
        if enabled is not None:
            blob["admin_toggles"] = {"moderation_ai": {"enabled": enabled, "surfaces": surfaces}}
    else:
        blob = {"config_version": "1.4"}
        if enabled is not None:
            blob["features"] = {"moderation_ai": {"enabled": enabled, "surfaces": surfaces}}
    row = OrganizationConfig(
        org_id=org.id, config=blob, creation_date=str(datetime.now()), update_date=str(datetime.now())
    )
    db.add(row)
    await db.commit()
    return row


@pytest.fixture
def factory(engine):
    f = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch.object(scheduler, "session_factory", return_value=f):
        yield f


def _result(action="flag", pii=0.9, tox=0.1, spam=0.1, integrity=None):
    return ModerationResult(
        pii=pii,
        toxicity=tox,
        spam=spam,
        academic_integrity=integrity,
        integrity_level="low",
        action=action,
        reasons=["x"] if action == "flag" else [],
    )


def _loader(text=LONG):
    async def _l(_s):
        return text

    return _l


async def _run(factory, text=LONG, *, content_type="discussion", uuid="d1", org_id=1, author=2, kind="forum_post"):
    await scheduler._run(
        kind=kind,
        content_type=content_type,
        content_uuid=uuid,
        org_id=org_id,
        author_user_id=author,
        text_loader=_loader(text),
    )


async def _flags(db):
    result = await db.execute(select(ModerationFlag).execution_options(populate_existing=True))
    return result.scalars().all()


MOD = "src.services.ai.jev.moderation.moderate_content"


# ---------------------------------------------------------------------------
# Org opt-in
# ---------------------------------------------------------------------------


class TestOptIn:
    def test_default_off(self):
        assert settings.org_opted_in({}) is False
        assert settings.org_opted_in({"config_version": "2.0"}) is False
        assert settings.org_opted_in({"config_version": "1.4"}) is False
        assert AdminToggles().moderation_ai.enabled is False

    def test_on_v2_and_v1(self):
        v2 = {"config_version": "2.0", "admin_toggles": {"moderation_ai": {"enabled": True}}}
        v1 = {"config_version": "1.4", "features": {"moderation_ai": {"enabled": True}}}
        assert settings.org_opted_in(v2) and settings.org_opted_in(v1)

    def test_surfaces_subset(self):
        cfg = {"config_version": "2.0", "admin_toggles": {"moderation_ai": {"enabled": True, "surfaces": ["discussion"]}}}
        assert settings.org_opted_in(cfg, "discussion")
        assert not settings.org_opted_in(cfg, "user_profile")

    def test_malformed_blob_is_opted_out(self):
        assert settings.org_opted_in({"config_version": "2.0", "admin_toggles": {"moderation_ai": "yes"}}) is False

    async def test_moderation_enabled_needs_platform_and_org(self, db, org, jev_on):
        await _config(db, org, enabled=True)
        assert await settings.moderation_enabled(org.id, db) is True
        assert await settings.moderation_enabled(None, db) is False

    async def test_moderation_enabled_false_when_org_off(self, db, org, jev_on):
        await _config(db, org, enabled=False)
        assert await settings.moderation_enabled(org.id, db) is False

    async def test_moderation_enabled_false_when_jev_off(self, db, org, jev_off):
        await _config(db, org, enabled=True)
        assert await settings.moderation_enabled(org.id, db) is False

    async def test_allowlist_not_required(self, db, org, jev_on):
        # Replaces allowed_org_ids for moderation only: empty list still works.
        await _config(db, org, enabled=True)
        assert await settings.moderation_enabled(org.id, db) is True


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class TestSchedule:
    async def test_noop_when_jev_disabled(self, jev_off):
        scheduler.schedule_moderation(
            kind="forum_post", content_type="discussion", content_uuid="d1",
            org_id=1, author_user_id=2, text_loader=_loader(),
        )
        assert not scheduler._background_tasks

    async def test_noop_for_unknown_type(self, jev_on):
        scheduler.schedule_moderation(
            kind="x", content_type="bogus", content_uuid="d1", org_id=1, author_user_id=2, text_loader=_loader()
        )
        assert not scheduler._background_tasks

    async def test_spawns_when_jev_on_and_drains(self, jev_on):
        with patch.object(scheduler, "_run", new_callable=AsyncMock) as run:
            scheduler.schedule_moderation(
                kind="forum_post", content_type="discussion", content_uuid="d1",
                org_id=1, author_user_id=2, text_loader=_loader(),
            )
            assert len(scheduler._background_tasks) == 1
            await scheduler.drain_moderation_tasks()
        run.assert_awaited_once()
        assert not scheduler._background_tasks

    def test_no_running_loop_never_raises(self, jev_on):
        scheduler.schedule_moderation(
            kind="forum_post", content_type="discussion", content_uuid="d1",
            org_id=1, author_user_id=2, text_loader=_loader(),
        )


class TestRun:
    async def test_does_nothing_when_org_not_opted_in(self, db, org, jev_on, factory):
        await _config(db, org, enabled=False)
        with patch(MOD, new_callable=AsyncMock) as m:
            await _run(factory)
        m.assert_not_awaited()
        assert await _flags(db) == []

    async def test_surface_not_selected_skips(self, db, org, jev_on, factory):
        await _config(db, org, enabled=True, surfaces=["user_profile"])
        with patch(MOD, new_callable=AsyncMock) as m:
            await _run(factory, content_type="discussion")
        m.assert_not_awaited()

    async def test_flag_recorded_only_on_flag_action(self, db, org, regular_user, jev_on, factory):
        await _config(db, org, enabled=True)
        with patch(MOD, new_callable=AsyncMock, return_value=_result("allow", pii=0.1)):
            await _run(factory, author=regular_user.id)
        assert await _flags(db) == []

        scheduler._scored.clear()
        scheduler._rate_seen.clear()
        with patch(MOD, new_callable=AsyncMock, return_value=_result("flag", pii=0.9)):
            await _run(factory, text=LONG + " again", author=regular_user.id)
        flags = await _flags(db)
        assert len(flags) == 1
        f = flags[0]
        assert f.status == "open" and f.severity == "high" and f.org_id == org.id
        assert f.scores["pii"] == 0.9 and f.reasons == ["Possible personal information"]

    async def test_no_text_persisted(self, db, org, regular_user, jev_on, factory):
        await _config(db, org, enabled=True)
        with patch(MOD, new_callable=AsyncMock, return_value=_result("flag")):
            await _run(factory, author=regular_user.id)
        (f,) = await _flags(db)
        blob = json.dumps(f.model_dump(), default=str)
        assert "555-0100" not in blob and "useless" not in blob
        assert len(f.content_hash) == 32
        assert set(ModerationFlag.model_fields) >= {"content_hash"}
        assert not {"text", "content", "body"} & set(ModerationFlag.model_fields)

    async def test_dedupe_same_text_scores_once(self, db, org, regular_user, jev_on, factory):
        await _config(db, org, enabled=True)
        with patch(MOD, new_callable=AsyncMock, return_value=_result("flag")) as m:
            await _run(factory, author=regular_user.id)
            await _run(factory, author=regular_user.id)
            # Even after the in-memory memo is gone, the recorded flag dedupes.
            scheduler._scored.clear()
            scheduler._rate_seen.clear()
            await _run(factory, author=regular_user.id)
        assert m.await_count == 1
        assert len(await _flags(db)) == 1

    async def test_edit_with_new_text_rescoring_adds_new_version(self, db, org, regular_user, jev_on, factory):
        await _config(db, org, enabled=True)
        with patch(MOD, new_callable=AsyncMock, return_value=_result("flag")) as m:
            await _run(factory, author=regular_user.id)
            scheduler._rate_seen.clear()  # past the 60s window
            await _run(factory, text=LONG + " edited", author=regular_user.id)
        assert m.await_count == 2
        assert len(await _flags(db)) == 2

    async def test_edit_within_window_is_scanned(self, db, org, regular_user, jev_on, factory):
        """Benign-then-edit inside the rate window must not evade scanning."""
        await _config(db, org, enabled=True)
        with patch(MOD, new_callable=AsyncMock, return_value=_result("allow")) as m:
            await _run(factory, author=regular_user.id)
            await _run(factory, text=LONG + " v2", author=regular_user.id)
            await _run(factory, text=LONG + " v3", uuid="other", author=regular_user.id)
        assert m.await_count == 3

    async def test_identical_resubmit_within_window_skipped(self, db, org, regular_user, jev_on, factory):
        await _config(db, org, enabled=True)
        # Unscorable result: not recorded as scored, so only the rate limiter can skip the repeat.
        with patch(MOD, new_callable=AsyncMock, return_value=None) as m:
            await _run(factory, author=regular_user.id)
            await _run(factory, author=regular_user.id)
        assert m.await_count == 1

    async def test_per_content_cap_limits_edits(self, db, org, regular_user, jev_on, factory):
        """6 distinct edits of one content inside 60s => only 5 provider calls."""
        await _config(db, org, enabled=True)
        with patch(MOD, new_callable=AsyncMock, return_value=_result("allow")) as m:
            for i in range(6):
                await _run(factory, text=LONG + f" v{i}", author=regular_user.id)
        assert m.await_count == scheduler.CONTENT_CALL_CAP == 5

    def test_content_cap_is_per_content(self):
        assert all(scheduler._acquire_content_slot("discussion:a") for _ in range(5))
        assert scheduler._acquire_content_slot("discussion:a") is False
        assert scheduler._acquire_content_slot("discussion:b") is True

    def test_redis_content_cap_is_one_transaction(self):
        from unittest.mock import MagicMock

        r = MagicMock()
        pipe = r.pipeline.return_value
        pipe.execute.return_value = [0, 1, 3, True]
        with patch("src.core.redis.get_redis_client", return_value=r):
            assert scheduler._acquire_content_slot("discussion:a") is True
        r.pipeline.assert_called_once_with(transaction=True)
        pipe.execute.assert_called_once()
        r.zremrangebyscore.assert_not_called()
        r.zadd.assert_not_called()
        r.zrem.assert_not_called()

        pipe.execute.return_value = [0, 1, scheduler.CONTENT_CALL_CAP + 1, True]
        with patch("src.core.redis.get_redis_client", return_value=r):
            assert scheduler._acquire_content_slot("discussion:a") is False
        r.zrem.assert_called_once()  # over-cap slot handed back

    async def test_capped_edit_gets_exactly_one_trailing_scan(self, db, org, regular_user, jev_on, factory):
        """5 edits scanned; 6th and 7th capped => after the window ONE scan of the 7th text."""
        await _config(db, org, enabled=True)
        clock = [1000.0]
        release = asyncio.Event()

        async def fake_wait(delay, wake):
            await release.wait()  # window "elapses" only when the test says so
            clock[0] += delay + 1

        with patch.object(scheduler, "_now", lambda: clock[0]), patch.object(
            scheduler, "_wait_window", fake_wait
        ), patch(MOD, new_callable=AsyncMock, return_value=_result("allow")) as m:
            for i in range(7):
                await _run(factory, text=LONG + f" v{i}", author=regular_user.id)
            assert m.await_count == 5
            assert len(scheduler._pending_trailing) == 1  # deduped to latest
            assert not any("text" in vars(e) for e in scheduler._pending_trailing.values())
            release.set()
            await asyncio.gather(*list(scheduler._background_tasks))
        assert m.await_count == 6
        assert m.await_args_list[-1].args[0] == (LONG + " v6").strip()
        assert not scheduler._pending_trailing

    async def test_shutdown_drain_runs_pending_trailing_scan(self, db, org, regular_user, jev_on, factory):
        await _config(db, org, enabled=True)
        clock = [1000.0]
        with patch.object(scheduler, "_now", lambda: clock[0]), patch(
            MOD, new_callable=AsyncMock, return_value=_result("allow")
        ) as m:
            for i in range(6):
                await _run(factory, text=LONG + f" v{i}", author=regular_user.id)
            assert len(scheduler._pending_trailing) == 1
            clock[0] += 61  # window elapsed by the time shutdown happens
            await asyncio.wait_for(scheduler.drain_moderation_tasks(), timeout=5)
        assert m.await_count == 6
        assert not scheduler._pending_trailing and not scheduler._background_tasks

    async def test_drain_drops_trailing_if_still_capped(self, db, org, regular_user, jev_on, factory):
        await _config(db, org, enabled=True)
        clock = [1000.0]
        with patch.object(scheduler, "_now", lambda: clock[0]), patch(
            MOD, new_callable=AsyncMock, return_value=_result("allow")
        ) as m:
            for i in range(6):
                await _run(factory, text=LONG + f" v{i}", author=regular_user.id)
            await asyncio.wait_for(scheduler.drain_moderation_tasks(), timeout=5)
        assert m.await_count == 5
        assert not scheduler._pending_trailing and not scheduler._background_tasks

    def test_rate_slot_key_includes_hash(self):
        assert scheduler._acquire_rate_slot("discussion:d1:h1") is True
        assert scheduler._acquire_rate_slot("discussion:d1:h2") is True
        assert scheduler._acquire_rate_slot("discussion:d1:h1") is False

    async def test_short_text_skipped(self, db, org, jev_on, factory):
        await _config(db, org, enabled=True)
        with patch(MOD, new_callable=AsyncMock) as m:
            await _run(factory, text="too short")
        m.assert_not_awaited()

    async def test_empty_text_skipped(self, db, org, jev_on, factory):
        await _config(db, org, enabled=True)
        with patch(MOD, new_callable=AsyncMock) as m:
            await _run(factory, text="")
        m.assert_not_awaited()

    async def test_jev_unavailable_fails_open(self, db, org, jev_on, factory):
        await _config(db, org, enabled=True)
        with patch(MOD, new_callable=AsyncMock, return_value=None):
            await _run(factory)
        assert await _flags(db) == []

    async def test_never_raises_on_any_failure(self, db, org, jev_on, factory):
        await _config(db, org, enabled=True)

        async def boom(_s):
            raise RuntimeError("loader exploded with secret text")

        # loader failure
        await scheduler._run(
            kind="forum_post", content_type="discussion", content_uuid="d1",
            org_id=1, author_user_id=2, text_loader=boom,
        )
        # Jev failure
        with patch(MOD, new_callable=AsyncMock, side_effect=ValueError("nope")):
            await _run(factory)
        # session factory failure
        with patch.object(scheduler, "session_factory", side_effect=RuntimeError("db down")):
            await _run(factory)

    async def test_failure_log_has_no_content(self, db, org, jev_on, factory, caplog):
        await _config(db, org, enabled=True)
        with patch(MOD, new_callable=AsyncMock, return_value=_result("flag")):
            with caplog.at_level("DEBUG", logger=scheduler.logger.name):
                await _run(factory, author=1)
        assert "555-0100" not in caplog.text and "useless" not in caplog.text

    async def test_profile_only_pii_and_toxicity(self, db, org, regular_user, jev_on, factory):
        await _config(db, org, enabled=True)
        with patch(MOD, new_callable=AsyncMock, return_value=_result("flag", pii=0.1, tox=0.1, spam=0.95)):
            await _run(
                factory, content_type="user_profile", uuid=regular_user.user_uuid,
                org_id=org.id, author=regular_user.id, kind="general",
            )
        assert await _flags(db) == []

        scheduler._scored.clear()
        scheduler._rate_seen.clear()
        with patch(MOD, new_callable=AsyncMock, return_value=_result("flag", pii=0.1, tox=0.95, spam=0.1)):
            await _run(
                factory, text=LONG + "!", content_type="user_profile", uuid=regular_user.user_uuid,
                org_id=org.id, author=regular_user.id, kind="general",
            )
        (f,) = await _flags(db)
        assert f.content_type == "user_profile" and f.kind == "general"

    async def test_profile_fans_out_to_opted_in_orgs(self, db, org, other_org, regular_user, jev_on, factory):
        await _config(db, org, enabled=True)
        with patch(MOD, new_callable=AsyncMock, return_value=_result("flag", pii=0.9)) as m:
            await scheduler._run(
                kind="general", content_type="user_profile", content_uuid=regular_user.user_uuid,
                org_id=None, author_user_id=regular_user.id, text_loader=_loader(),
            )
        assert m.await_count == 1
        assert [f.org_id for f in await _flags(db)] == [org.id]

    async def test_integrity_only_for_assignments_and_high_severity(self, db, org, regular_user, jev_on, factory):
        await _config(db, org, enabled=True)
        res = _result("flag", pii=0.1, integrity=0.9)
        with patch(MOD, new_callable=AsyncMock, return_value=res) as m:
            await _run(
                factory, content_type="assignment_submission", kind="assignment_submission",
                uuid="aus1", author=regular_user.id,
            )
        assert m.await_args.kwargs["kind"] == "assignment_submission"
        assert m.await_args.kwargs["org_id"] is None  # allow-list bypassed on purpose
        (f,) = await _flags(db)
        assert f.severity == "high"
        assert f.reasons == ["Possible integrity concern - review the work yourself"]
        assert f.scores["academic_integrity"] == 0.9


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


class TestExtraction:
    def test_short_answer_and_code(self):
        assert task_text("SHORT_ANSWER", {"answer": " hello "}) == "hello"
        assert task_text(AssignmentTaskTypeEnum.CODE, {"source_code": "print(1)", "language_id": 71}) == "print(1)"

    def test_form_collects_blank_answers_only(self):
        data = {"submissions": [
            {"questionUUID": "q", "blankUUID": "b", "answer": "photosynthesis"},
            {"questionUUID": "q", "blankUUID": "b2", "answer": "  "},
        ]}
        assert task_text("FORM", data) == "photosynthesis"

    def test_quiz_option_uuids_and_files_skipped(self):
        assert task_text("QUIZ", {"answers": ["8f14e45f-ceea-467a-9575-1a0d1e1d1d1d"]}) == ""
        assert task_text("FILE_SUBMISSION", {"file_uuid": "abc", "files": ["x.pdf"]}) == ""
        assert task_text("NUMBER_ANSWER", {"answer": "42"}) == ""

    def test_custom_skips_ids_and_file_keys(self):
        data = {
            "essay": "A real paragraph of student writing.",
            "id": "8f14e45f-ceea-467a-9575-1a0d1e1d1d1d",
            "files": ["a.pdf"],
            "nested": {"note": "second thought"},
        }
        out = task_text("CUSTOM", data)
        assert "real paragraph" in out and "second thought" in out
        assert "8f14e45f" not in out and "a.pdf" not in out

    async def test_forum_and_profile_loaders(self):
        tiptap = json.dumps({"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "hello world"}]}]})
        assert "hello world" in await forum_text("Title", tiptap)(None)
        assert await profile_text("bio here", "Ada", "Lovelace")(None) == "Ada Lovelace\nbio here"
        assert await profile_text(None, None, None)(None) == ""

    async def test_assignment_loader_reads_only_text_tasks(self, db, org, course, chapter, activity, regular_user):
        a = Assignment(
            title="A", description="d", due_date="2030-01-01", published=True,
            grading_type=GradingTypeEnum.NUMERIC, org_id=org.id, course_id=course.id,
            chapter_id=chapter.id, activity_id=activity.id, assignment_uuid="assignment_mod",
            creation_date=str(datetime.now()), update_date=str(datetime.now()),
        )
        db.add(a)
        await db.commit()
        await db.refresh(a)

        async def add_task(i, kind, sub):
            t = AssignmentTask(
                title="t", description="d", hint="", reference_file=None, assignment_type=kind,
                contents={}, max_grade_value=10, assignment_id=a.id, org_id=org.id,
                course_id=course.id, chapter_id=chapter.id, activity_id=activity.id,
                assignment_task_uuid=f"assignmenttask_mod_{i}",
                creation_date=str(datetime.now()), update_date=str(datetime.now()),
            )
            db.add(t)
            await db.commit()
            await db.refresh(t)
            db.add(AssignmentTaskSubmission(
                assignment_task_submission_uuid=f"ats_mod_{i}", task_submission=sub,
                grade=0, task_submission_grade_feedback="", assignment_type=kind,
                user_id=regular_user.id, activity_id=activity.id, course_id=course.id,
                chapter_id=chapter.id, assignment_task_id=t.id,
                creation_date=str(datetime.now()), update_date=str(datetime.now()),
            ))
            await db.commit()

        await add_task(1, AssignmentTaskTypeEnum.SHORT_ANSWER, {"answer": "my written answer"})
        await add_task(2, AssignmentTaskTypeEnum.QUIZ, {"answers": ["8f14e45f-ceea-467a-9575-1a0d1e1d1d1d"]})
        await add_task(3, AssignmentTaskTypeEnum.FILE_SUBMISSION, {"file": "x.pdf"})
        text = await assignment_submission_text(regular_user.id, a.id)(db)
        assert text == "my written answer"


# ---------------------------------------------------------------------------
# Hook sites: each calls schedule_moderation exactly once with the right args
# ---------------------------------------------------------------------------


async def _community(db, org):
    c = Community(
        org_id=org.id, name="C", description="d", public=True, thumbnail_image="",
        community_uuid="community_mod", moderation_words=[],
        creation_date="2024-01-01", update_date="2024-01-01",
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


class TestHookSites:
    async def test_discussion_create_and_update(self, db, org, admin_user, mock_request):
        from src.services.communities.discussions import create_discussion, update_discussion

        community = await _community(db, org)
        d = "src.services.communities.discussions."
        with patch(d + "schedule_moderation") as sched, patch(
            d + "authorization_verify_if_user_is_anon", new_callable=AsyncMock
        ), patch(d + "check_resource_access", new_callable=AsyncMock), patch(
            d + "validate_discussion_content", new_callable=AsyncMock
        ), patch(d + "track", new_callable=AsyncMock), patch(
            d + "dispatch_webhooks", new_callable=AsyncMock
        ), patch(
            d + "authorization_verify_based_on_org_admin_status", new_callable=AsyncMock, return_value=True
        ):
            created = await create_discussion(
                mock_request, community.community_uuid, "Title", "Body text", "general", admin_user, db
            )
            sched.assert_called_once()
            kw = sched.call_args.kwargs
            assert (kw["kind"], kw["content_type"]) == ("forum_post", "discussion")
            assert kw["content_uuid"] == created.discussion_uuid
            assert kw["org_id"] == org.id and kw["author_user_id"] == admin_user.id
            assert await kw["text_loader"](None) == "Title\nBody text"

            sched.reset_mock()
            await update_discussion(
                mock_request, created.discussion_uuid, DiscussionUpdate(content="Edited"), admin_user, db
            )
            sched.assert_called_once()
            assert sched.call_args.kwargs["content_type"] == "discussion"
            assert sched.call_args.kwargs["author_user_id"] == admin_user.id

    async def test_comment_create_and_update(self, db, org, admin_user, regular_user, mock_request):
        from src.services.communities.comments import create_comment, update_comment

        community = await _community(db, org)
        disc = Discussion(
            title="T", content="C", label="general", community_id=community.id, org_id=org.id,
            author_id=admin_user.id, discussion_uuid="discussion_mod",
            creation_date="2024-01-01", update_date="2024-01-01",
        )
        db.add(disc)
        await db.commit()
        c = "src.services.communities.comments."
        with patch(c + "schedule_moderation") as sched, patch(
            c + "authorization_verify_if_user_is_anon", new_callable=AsyncMock
        ), patch(c + "check_resource_access", new_callable=AsyncMock), patch(
            c + "validate_comment_content", new_callable=AsyncMock
        ), patch(c + "dispatch_webhooks", new_callable=AsyncMock), patch(
            c + "get_user_votes_for_comments", new_callable=AsyncMock, return_value={}
        ):
            created = await create_comment(mock_request, "discussion_mod", "A comment", regular_user, db)
            sched.assert_called_once()
            kw = sched.call_args.kwargs
            assert kw["content_type"] == "discussion_comment" and kw["kind"] == "forum_post"
            assert kw["content_uuid"] == created.comment_uuid
            assert kw["org_id"] == org.id and kw["author_user_id"] == regular_user.id

            sched.reset_mock()
            await update_comment(
                mock_request, created.comment_uuid, DiscussionCommentUpdate(content="Edited"), regular_user, db
            )
            sched.assert_called_once()
            assert sched.call_args.kwargs["org_id"] == org.id
            assert await sched.call_args.kwargs["text_loader"](None) == "Edited"

    async def test_profile_update(self, db, regular_user, mock_request):
        from src.services.users.users import update_user

        with patch("src.services.users.users.schedule_moderation") as sched, patch(
            "src.services.users.users.rbac_check", new_callable=AsyncMock
        ):
            await update_user(
                request=mock_request, db_session=db, user_id=regular_user.id, current_user=regular_user,
                user_object=UserUpdate(
                    username="regular", first_name="Regular", last_name="Person",
                    email="regular@test.com", bio="I like chess",
                ),
            )
        sched.assert_called_once()
        kw = sched.call_args.kwargs
        assert kw["content_type"] == "user_profile" and kw["kind"] == "general"
        assert kw["org_id"] is None and kw["author_user_id"] == regular_user.id
        assert kw["content_uuid"] == regular_user.user_uuid
        assert await kw["text_loader"](None) == "Regular Person\nI like chess"

    async def test_assignment_submission_finalize(
        self, db, org, course, chapter, activity, regular_user, mock_request
    ):
        from src.services.courses.activities.assignments import create_assignment_submission

        a = Assignment(
            title="Essay", description="d", due_date="2030-01-01", published=True,
            grading_type=GradingTypeEnum.NUMERIC, auto_grading=False, ungraded=True,
            org_id=org.id, course_id=course.id, chapter_id=chapter.id, activity_id=activity.id,
            assignment_uuid="assignment_hook",
            creation_date=str(datetime.now()), update_date=str(datetime.now()),
        )
        db.add(a)
        await db.commit()
        await db.refresh(a)
        trail = Trail(
            org_id=org.id, user_id=regular_user.id, trail_uuid="trail_hook",
            creation_date=str(datetime.now()), update_date=str(datetime.now()),
        )
        db.add(trail)
        await db.commit()
        await db.refresh(trail)

        p = "src.services.courses.activities.assignments."
        with patch(p + "schedule_moderation") as sched, patch(
            p + "check_resource_access", new_callable=AsyncMock
        ), patch(p + "authorization_verify_based_on_roles", new_callable=AsyncMock, return_value=False), patch(
            p + "check_trail_presence", new_callable=AsyncMock, return_value=trail
        ), patch(p + "check_course_completion_and_create_certificate", new_callable=AsyncMock), patch(
            p + "is_course_fully_completed", new_callable=AsyncMock, return_value=False
        ), patch(p + "track", new_callable=AsyncMock), patch(
            p + "dispatch_webhooks", new_callable=AsyncMock
        ), patch(p + "record_audit_event", new_callable=AsyncMock):
            await create_assignment_submission(mock_request, a.assignment_uuid, regular_user, db)

        sched.assert_called_once()
        kw = sched.call_args.kwargs
        assert kw["kind"] == "assignment_submission" == kw["content_type"]
        from src.db.courses.assignments import AssignmentUserSubmission

        row = (await db.execute(select(AssignmentUserSubmission))).scalars().one()
        assert kw["content_uuid"] == row.assignmentusersubmission_uuid
        assert kw["org_id"] == org.id and kw["author_user_id"] == regular_user.id
        assert callable(kw["text_loader"])

    def test_autosave_path_is_not_hooked(self):
        import inspect

        from src.services.courses.activities import assignments as mod

        assert "schedule_moderation" not in inspect.getsource(mod.handle_assignment_task_submission)
