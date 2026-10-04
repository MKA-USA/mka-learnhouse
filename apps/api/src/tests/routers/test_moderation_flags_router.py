"""Moderation flag API: staff-only RBAC, contract shape, review actions, org toggle."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from src.core.events.database import get_db_session
from src.db.moderation_flags import ModerationFlag
from src.db.organization_config import OrganizationConfig
from src.routers.moderation_flags import org_settings_router
from src.routers.moderation_flags import router as flags_router
from src.security.auth import get_authenticated_user

CURRENT = {"user": None}


@pytest.fixture
def app(db):
    app = FastAPI()
    app.include_router(flags_router, prefix="/api/v1/moderation-flags")
    app.include_router(org_settings_router, prefix="/api/v1/orgs")
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_authenticated_user] = lambda: CURRENT["user"]
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _flag(db, org, author, *, uuid="modflag_1", status="open", ctype="user_profile", cuuid=None, created=None):
    f = ModerationFlag(
        flag_uuid=uuid,
        org_id=org.id,
        content_type=ctype,
        content_uuid=cuuid or author.user_uuid,
        content_hash=f"h-{uuid}",
        author_user_id=author.id,
        kind="general",
        scores={"pii": 0.9, "toxicity": 0.1, "spam": 0.0, "academic_integrity": None},
        reasons=["Possible personal information"],
        severity="high",
        status=status,
        created_at=created or datetime.now().isoformat(),
    )
    db.add(f)
    await db.commit()
    return f


BASE = "/api/v1/moderation-flags"


class TestRbac:
    async def test_student_denied_everywhere(self, client, db, org, admin_user, regular_user):
        await _flag(db, org, regular_user)
        CURRENT["user"] = regular_user
        assert (await client.get(f"{BASE}/orgs/{org.id}")).status_code == 403
        assert (await client.get(f"{BASE}/orgs/{org.id}/by-content?content_uuid=x")).status_code == 403
        # Non-staff, non-instructor: nothing is ever disclosed (and the author never sees own flags).
        r = await client.get(f"{BASE}/orgs/{org.id}/by-user/{regular_user.user_uuid}")
        assert r.status_code == 200 and r.json() == {"items": []}
        # Author cannot see or touch their own flag.
        assert (await client.patch(f"{BASE}/modflag_1", json={"status": "dismissed"})).status_code == 404
        row = (await db.execute(select(ModerationFlag))).scalars().one()
        assert row.status == "open"

    async def test_staff_allowed(self, client, db, org, admin_user, regular_user):
        await _flag(db, org, regular_user)
        CURRENT["user"] = admin_user
        r = await client.get(f"{BASE}/orgs/{org.id}")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    async def test_mfa_check_failure_fails_closed(self, client, db, org, admin_user, regular_user):
        """An unexpected error in the MFA check must never grant access."""
        await _flag(db, org, regular_user)
        CURRENT["user"] = admin_user
        with patch("src.security.org_auth.enforce_org_mfa", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                await client.get(f"{BASE}/orgs/{org.id}")
            with pytest.raises(RuntimeError):
                await client.get(f"{BASE}/orgs/{org.id}/by-content?content_uuid=x")

    async def test_cross_org_staff_denied(self, client, db, org, other_org, admin_user, regular_user):
        await _flag(db, org, regular_user)
        CURRENT["user"] = admin_user  # admin of org, NOT of other_org
        assert (await client.get(f"{BASE}/orgs/{other_org.id}")).status_code == 403
        # and an other-org admin cannot read org's flags
        from src.db.roles import Role, RoleTypeEnum
        from src.db.user_organizations import UserOrganization
        from src.db.users import PublicUser, User
        from src.tests.conftest import ADMIN_RIGHTS

        db.add(Role(id=9, name="Admin2", org_id=other_org.id, role_type=RoleTypeEnum.TYPE_ORGANIZATION,
                    role_uuid="role_admin2", rights=ADMIN_RIGHTS.model_dump(),
                    creation_date=str(datetime.now()), update_date=str(datetime.now())))
        u = User(id=9, username="oadmin", first_name="O", last_name="A", email="o@a.com", password="x",
                 user_uuid="user_oadmin", creation_date=str(datetime.now()), update_date=str(datetime.now()))
        db.add(u)
        await db.commit()
        db.add(UserOrganization(user_id=9, org_id=other_org.id, role_id=9,
                                creation_date=str(datetime.now()), update_date=str(datetime.now())))
        await db.commit()
        CURRENT["user"] = PublicUser(id=9, username="oadmin", first_name="O", last_name="A",
                                     email="o@a.com", user_uuid="user_oadmin")
        assert (await client.get(f"{BASE}/orgs/{org.id}")).status_code == 403
        assert (await client.patch(f"{BASE}/modflag_1", json={"status": "reviewed"})).status_code == 404

    async def test_community_moderator_role_allowed(self, client, db, org, regular_user):
        from src.db.roles import Role, RoleTypeEnum
        from src.db.user_organizations import UserOrganization
        from src.tests.conftest import USER_RIGHTS

        rights = USER_RIGHTS.model_dump()
        rights["communities"]["action_update"] = True
        db.add(Role(id=7, name="Mod", org_id=org.id, role_type=RoleTypeEnum.TYPE_ORGANIZATION,
                    role_uuid="role_mod", rights=rights,
                    creation_date=str(datetime.now()), update_date=str(datetime.now())))
        await db.commit()
        uo = (await db.execute(select(UserOrganization).where(UserOrganization.user_id == regular_user.id))).scalars().one()
        uo.role_id = 7
        db.add(uo)
        await db.commit()
        CURRENT["user"] = regular_user
        assert (await client.get(f"{BASE}/orgs/{org.id}")).status_code == 200
        # ...but a moderator still cannot change the org-level AI toggle.
        assert (await client.put(f"/api/v1/orgs/{org.id}/config/ai-moderation", json={"enabled": True})).status_code == 403

    async def test_unknown_org_404(self, client, admin_user):
        CURRENT["user"] = admin_user
        assert (await client.get(f"{BASE}/orgs/999")).status_code == 404

    async def test_api_token_user_denied(self, client, org):
        from src.db.users import APITokenUser

        CURRENT["user"] = MagicMock(spec=APITokenUser)
        assert (await client.get(f"{BASE}/orgs/{org.id}")).status_code == 403


class TestListing:
    async def test_contract_shape_and_filters(self, client, db, org, admin_user, regular_user):
        await _flag(db, org, regular_user, uuid="f_open")
        await _flag(db, org, regular_user, uuid="f_done", status="reviewed", ctype="discussion", cuuid="d1")
        CURRENT["user"] = admin_user

        r = await client.get(f"{BASE}/orgs/{org.id}")
        body = r.json()
        assert body["total"] == 1 and [i["flag_uuid"] for i in body["items"]] == ["f_open"]
        item = body["items"][0]
        assert set(item) == {
            "flag_uuid", "org_id", "content_type", "content_uuid", "author_user_uuid", "kind",
            "severity", "scores", "reasons", "status", "reviewed_by_user_uuid", "reviewed_at",
            "created_at", "content_link",
        }
        assert set(item["scores"]) == {"pii", "toxicity", "spam", "academic_integrity"}
        assert item["author_user_uuid"] == regular_user.user_uuid
        assert item["content_link"] == f"/dash/users/analytics/{regular_user.id}"
        assert item["reasons"] == ["Possible personal information"]

        assert (await client.get(f"{BASE}/orgs/{org.id}?status=all")).json()["total"] == 2
        assert (await client.get(f"{BASE}/orgs/{org.id}?status=reviewed")).json()["total"] == 1
        assert (await client.get(f"{BASE}/orgs/{org.id}?status=all&content_type=discussion")).json()["total"] == 1
        assert (await client.get(f"{BASE}/orgs/{org.id}?status=bogus")).status_code == 422
        assert (await client.get(f"{BASE}/orgs/{org.id}?content_type=bogus")).status_code == 422

    async def test_pagination(self, client, db, org, admin_user, regular_user):
        for i in range(3):
            await _flag(db, org, regular_user, uuid=f"f{i}", created=f"2026-01-0{i + 1}T00:00:00")
        CURRENT["user"] = admin_user
        r = (await client.get(f"{BASE}/orgs/{org.id}?limit=2&offset=0")).json()
        assert r["total"] == 3 and [i["flag_uuid"] for i in r["items"]] == ["f2", "f1"]
        r = (await client.get(f"{BASE}/orgs/{org.id}?limit=2&offset=2")).json()
        assert [i["flag_uuid"] for i in r["items"]] == ["f0"]

    async def test_by_content_and_by_user(self, client, db, org, admin_user, regular_user):
        await _flag(db, org, regular_user, uuid="a", ctype="discussion", cuuid="disc_1")
        await _flag(db, org, regular_user, uuid="b", ctype="discussion", cuuid="disc_2")
        CURRENT["user"] = admin_user
        r = (await client.get(f"{BASE}/orgs/{org.id}/by-content?content_type=discussion&content_uuid=disc_1")).json()
        assert [i["flag_uuid"] for i in r["items"]] == ["a"]
        r = (await client.get(f"{BASE}/orgs/{org.id}/by-user/{regular_user.user_uuid}")).json()
        assert {i["flag_uuid"] for i in r["items"]} == {"a", "b"}
        assert (await client.get(f"{BASE}/orgs/{org.id}/by-user/nobody")).json() == {"items": []}


class TestReview:
    async def test_patch_status_cycle(self, client, db, org, admin_user, regular_user):
        await _flag(db, org, regular_user)
        CURRENT["user"] = admin_user
        r = await client.patch(f"{BASE}/modflag_1", json={"status": "reviewed"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "reviewed"
        assert body["reviewed_by_user_uuid"] == admin_user.user_uuid and body["reviewed_at"]

        r = await client.patch(f"{BASE}/modflag_1", json={"status": "dismissed"})
        assert r.json()["status"] == "dismissed"

        r = await client.patch(f"{BASE}/modflag_1", json={"status": "open"})
        body = r.json()
        assert body["status"] == "open" and body["reviewed_by_user_uuid"] is None and body["reviewed_at"] is None

    async def test_patch_validates_and_404s(self, client, db, org, admin_user, regular_user):
        await _flag(db, org, regular_user)
        CURRENT["user"] = admin_user
        assert (await client.patch(f"{BASE}/modflag_1", json={"status": "deleted"})).status_code == 422
        assert (await client.patch(f"{BASE}/nope", json={"status": "reviewed"})).status_code == 404


class TestOrgToggle:
    URL = "/api/v1/orgs/{}/config/ai-moderation"

    async def _cfg(self, db, org, blob):
        db.add(OrganizationConfig(org_id=org.id, config=blob, creation_date="x", update_date="x"))
        await db.commit()

    async def test_default_off(self, client, db, org, admin_user):
        await self._cfg(db, org, {"config_version": "2.0"})
        CURRENT["user"] = admin_user
        r = await client.get(self.URL.format(org.id))
        assert r.status_code == 200 and r.json()["enabled"] is False
        assert set(r.json()["surfaces"]) == {"discussion", "discussion_comment", "assignment_submission", "user_profile"}

    async def test_put_enables_v2_and_v1(self, client, db, org, admin_user):
        await self._cfg(db, org, {"config_version": "2.0", "admin_toggles": {}})
        CURRENT["user"] = admin_user
        r = await client.put(self.URL.format(org.id), json={"enabled": True, "surfaces": ["discussion"]})
        assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["surfaces"] == ["discussion"]
        row = (await db.execute(select(OrganizationConfig))).scalars().one()
        assert row.config["admin_toggles"]["moderation_ai"] == {"enabled": True, "surfaces": ["discussion"]}

        r = await client.put(self.URL.format(org.id), json={"enabled": True})
        assert r.json()["surfaces"] and len(r.json()["surfaces"]) == 4
        r = await client.put(self.URL.format(org.id), json={"enabled": False})
        assert r.json()["enabled"] is False

    async def test_put_v1_config(self, client, db, org, admin_user):
        await self._cfg(db, org, {"config_version": "1.4", "features": {}})
        CURRENT["user"] = admin_user
        assert (await client.put(self.URL.format(org.id), json={"enabled": True})).status_code == 200
        row = (await db.execute(select(OrganizationConfig))).scalars().one()
        assert row.config["features"]["moderation_ai"]["enabled"] is True

    async def test_put_admin_only(self, client, db, org, admin_user, regular_user):
        await self._cfg(db, org, {"config_version": "2.0"})
        CURRENT["user"] = regular_user
        assert (await client.put(self.URL.format(org.id), json={"enabled": True})).status_code == 403
        assert (await client.get(self.URL.format(org.id))).status_code == 403
        row = (await db.execute(select(OrganizationConfig))).scalars().one()
        assert "admin_toggles" not in row.config

    async def test_put_validates_body(self, client, db, org, admin_user):
        await self._cfg(db, org, {"config_version": "2.0"})
        CURRENT["user"] = admin_user
        assert (await client.put(self.URL.format(org.id), json={"enabled": "maybe"})).status_code == 422
        assert (await client.put(self.URL.format(org.id), json={})).status_code == 422
        assert (await client.put(self.URL.format(org.id), json={"enabled": True, "surfaces": ["files"]})).status_code == 422

    async def test_provider_available_flag(self, client, db, org, admin_user):
        await self._cfg(db, org, {"config_version": "2.0"})
        CURRENT["user"] = admin_user
        with patch("src.services.moderation_ai.settings.jev_available", return_value=False):
            assert (await client.get(self.URL.format(org.id))).json()["provider_available"] is False


# ---------------------------------------------------------------------------
# content_link shapes (must match the web routes, which add uuid prefixes)
# ---------------------------------------------------------------------------


class TestContentLinks:
    async def test_discussion_and_comment_links_unprefixed(self, db, org, admin_user, regular_user):
        from src.db.communities.communities import Community
        from src.db.communities.discussion_comments import DiscussionComment
        from src.db.communities.discussions import Discussion
        from src.services.moderation_ai.service import _content_link

        c = Community(org_id=org.id, name="C", description="d", public=True, thumbnail_image="",
                      community_uuid="community_abc", moderation_words=[],
                      creation_date="2024-01-01", update_date="2024-01-01")
        db.add(c)
        await db.commit()
        await db.refresh(c)
        d = Discussion(title="T", content="C", label="general", community_id=c.id, org_id=org.id,
                       author_id=regular_user.id, discussion_uuid="discussion_xyz")
        db.add(d)
        await db.commit()
        await db.refresh(d)
        db.add(DiscussionComment(comment_uuid="comment_q", content="x", discussion_id=d.id,
                                 org_id=org.id, author_id=regular_user.id,
                                 creation_date="2024-01-01", update_date="2024-01-01"))
        await db.commit()

        f1 = await _flag(db, org, regular_user, uuid="l1", ctype="discussion", cuuid="discussion_xyz")
        f2 = await _flag(db, org, regular_user, uuid="l2", ctype="discussion_comment", cuuid="comment_q")
        assert await _content_link(f1, db) == "/community/abc/discussion/xyz"
        assert await _content_link(f2, db) == "/community/abc/discussion/xyz"

    async def test_assignment_submission_link(self, db, org, regular_user, course, chapter, activity):
        from src.services.moderation_ai.service import _content_link

        _, sub = await _assignment(db, org, course, chapter, activity, regular_user)
        f = await _flag(db, org, regular_user, uuid="l3", ctype="assignment_submission", cuuid=sub.assignmentusersubmission_uuid)
        assert await _content_link(f, db) == "/dash/assignments/mod?subpage=submissions"

    async def test_user_profile_link_uses_numeric_id(self, db, org, regular_user):
        from src.services.moderation_ai.service import _content_link

        f = await _flag(db, org, regular_user, uuid="l4")
        link = await _content_link(f, db)
        assert link == f"/dash/users/analytics/{regular_user.id}"
        assert link.startswith("/") and "user_" not in link


async def _assignment(db, org, course, chapter, activity, student, suffix="mod"):
    from src.db.courses.assignments import Assignment, AssignmentUserSubmission, GradingTypeEnum

    a = Assignment(
        title="A", description="d", due_date="2030-01-01", published=True,
        grading_type=GradingTypeEnum.NUMERIC, org_id=org.id, course_id=course.id,
        chapter_id=chapter.id, activity_id=activity.id, assignment_uuid=f"assignment_{suffix}",
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    sub = AssignmentUserSubmission(
        grade=0, user_id=student.id, assignment_id=a.id,
        assignmentusersubmission_uuid=f"assignmentusersubmission_{suffix}",
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return a, sub


# ---------------------------------------------------------------------------
# Authors never see flags about their own content
# ---------------------------------------------------------------------------


class TestOwnContentExcluded:
    async def test_admin_does_not_see_flags_on_own_content(self, client, db, org, admin_user, regular_user):
        await _flag(db, org, admin_user, uuid="mine", ctype="discussion", cuuid="d_mine")
        await _flag(db, org, regular_user, uuid="theirs", ctype="discussion", cuuid="d_theirs")
        CURRENT["user"] = admin_user
        r = (await client.get(f"{BASE}/orgs/{org.id}?status=all")).json()
        assert [i["flag_uuid"] for i in r["items"]] == ["theirs"] and r["total"] == 1
        r = (await client.get(f"{BASE}/orgs/{org.id}/by-content?content_uuid=d_mine")).json()
        assert r["items"] == []
        r = (await client.get(f"{BASE}/orgs/{org.id}/by-user/{admin_user.user_uuid}")).json()
        assert r["items"] == []
        assert (await client.patch(f"{BASE}/mine", json={"status": "dismissed"})).status_code == 404


# ---------------------------------------------------------------------------
# Instructors read flags for submissions in courses they teach (not the queue)
# ---------------------------------------------------------------------------


async def _instructor(db, org, uid, name, author_of=None, update_own=True):
    from src.db.resource_authors import ResourceAuthor, ResourceAuthorshipEnum, ResourceAuthorshipStatusEnum
    from src.db.roles import Role, RoleTypeEnum
    from src.db.user_organizations import UserOrganization
    from src.db.users import PublicUser, User
    from src.tests.conftest import USER_RIGHTS

    rights = USER_RIGHTS.model_dump()
    rights["courses"]["action_update_own"] = update_own
    db.add(Role(id=uid, name=f"Instr{uid}", org_id=org.id, role_type=RoleTypeEnum.TYPE_ORGANIZATION,
                role_uuid=f"role_i{uid}", rights=rights,
                creation_date=str(datetime.now()), update_date=str(datetime.now())))
    db.add(User(id=uid, username=name, first_name=name, last_name="I", email=f"{name}@t.com", password="x",
                user_uuid=f"user_{name}", creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    db.add(UserOrganization(user_id=uid, org_id=org.id, role_id=uid,
                            creation_date=str(datetime.now()), update_date=str(datetime.now())))
    if author_of:
        db.add(ResourceAuthor(resource_uuid=author_of, user_id=uid, authorship=ResourceAuthorshipEnum.CREATOR,
                              authorship_status=ResourceAuthorshipStatusEnum.ACTIVE))
    await db.commit()
    return PublicUser(id=uid, username=name, first_name=name, last_name="I",
                      email=f"{name}@t.com", user_uuid=f"user_{name}")


class TestAssignmentInstructorAccess:
    async def _setup(self, db, org, course, chapter, activity, regular_user):
        _, sub = await _assignment(db, org, course, chapter, activity, regular_user)
        await _flag(db, org, regular_user, uuid="sf", ctype="assignment_submission",
                    cuuid=sub.assignmentusersubmission_uuid)
        await _flag(db, org, regular_user, uuid="pf", ctype="user_profile")
        return sub.assignmentusersubmission_uuid

    async def test_course_instructor_can_read_submission_flags_only(
        self, client, db, org, course, chapter, activity, regular_user
    ):
        sub_uuid = await self._setup(db, org, course, chapter, activity, regular_user)
        teacher = await _instructor(db, org, 5, "teach", author_of=course.course_uuid)
        CURRENT["user"] = teacher
        r = await client.get(f"{BASE}/orgs/{org.id}/by-content?content_type=assignment_submission&content_uuid={sub_uuid}")
        assert r.status_code == 200 and [i["flag_uuid"] for i in r.json()["items"]] == ["sf"]
        r = await client.get(f"{BASE}/orgs/{org.id}/by-user/{regular_user.user_uuid}")
        assert r.status_code == 200 and [i["flag_uuid"] for i in r.json()["items"]] == ["sf"]  # profile flag excluded
        # Org-wide queue and review stay staff-only.
        assert (await client.get(f"{BASE}/orgs/{org.id}")).status_code == 403
        assert (await client.patch(f"{BASE}/sf", json={"status": "reviewed"})).status_code == 404
        # Cannot use by-content for non-submission content.
        assert (await client.get(f"{BASE}/orgs/{org.id}/by-content?content_type=user_profile&content_uuid={regular_user.user_uuid}")).status_code == 403
        assert (await client.get(f"{BASE}/orgs/{org.id}/by-content?content_uuid={sub_uuid}")).status_code == 403

    async def test_other_course_instructor_denied(self, client, db, org, course, chapter, activity, regular_user):
        sub_uuid = await self._setup(db, org, course, chapter, activity, regular_user)
        other = await _instructor(db, org, 6, "other", author_of="course_elsewhere")
        CURRENT["user"] = other
        r = await client.get(f"{BASE}/orgs/{org.id}/by-content?content_type=assignment_submission&content_uuid={sub_uuid}")
        assert r.status_code == 403
        r = await client.get(f"{BASE}/orgs/{org.id}/by-user/{regular_user.user_uuid}")
        assert r.status_code == 200 and r.json()["items"] == []

    async def test_cross_org_instructor_denied(
        self, client, db, org, other_org, course, chapter, activity, regular_user
    ):
        sub_uuid = await self._setup(db, org, course, chapter, activity, regular_user)
        outsider = await _instructor(db, other_org, 7, "outsider", author_of=course.course_uuid)
        CURRENT["user"] = outsider
        assert (await client.get(f"{BASE}/orgs/{org.id}/by-content?content_type=assignment_submission&content_uuid={sub_uuid}")).status_code == 403
        assert (await client.get(f"{BASE}/orgs/{org.id}/by-user/{regular_user.user_uuid}")).status_code == 403

    async def test_student_denied(self, client, db, org, course, chapter, activity, regular_user):
        sub_uuid = await self._setup(db, org, course, chapter, activity, regular_user)
        classmate = await _instructor(db, org, 8, "mate")  # same role rights, not an author of the course
        CURRENT["user"] = classmate
        assert (await client.get(f"{BASE}/orgs/{org.id}/by-content?content_type=assignment_submission&content_uuid={sub_uuid}")).status_code == 403
        assert (await client.get(f"{BASE}/orgs/{org.id}/by-user/{regular_user.user_uuid}")).json()["items"] == []


class TestByUserStudentShortCircuit:
    async def test_student_by_user_never_queries_flags(self, client, db, org, course, chapter, activity, regular_user):
        """No assignment-flag lookup for callers without instructor rights (no timing oracle)."""
        _, sub = await _assignment(db, org, course, chapter, activity, regular_user)
        await _flag(db, org, regular_user, uuid="sf", ctype="assignment_submission",
                    cuuid=sub.assignmentusersubmission_uuid)
        student = await _instructor(db, org, 9, "stud", update_own=False)
        CURRENT["user"] = student
        seen: list[str] = []
        real_execute = db.execute

        async def spy(stmt, *a, **kw):
            seen.append(str(stmt))
            return await real_execute(stmt, *a, **kw)

        with patch.object(db, "execute", spy):
            r = await client.get(f"{BASE}/orgs/{org.id}/by-user/{regular_user.user_uuid}")
        assert r.status_code == 200 and r.json() == {"items": []}
        assert not any("moderation_flag" in q for q in seen)
