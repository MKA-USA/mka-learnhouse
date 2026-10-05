"""Seeded world for the /mka/compliance tests (synthetic ``example.invalid`` data only).

Org 1 (``org``)   cycle "2026-27" (2026-11-01 .. 2026-12-01), general course G, department courses T (tabligh, with
                  a contact-check assignment) and M (maal), a 10-row expected roster, 5 learners with progress.
Org 2 (``other_org``) the same label, its own course and roster, one user who is ALSO on org 1's roster by email
                  but is not an org-1 member (must stay ``not_signed_in`` in org 1).
"""

from datetime import date, datetime
from types import SimpleNamespace

from sqlmodel import select

from src.db.courses.activities import Activity, ActivitySubTypeEnum, ActivityTypeEnum
from src.db.courses.assignments import (
    Assignment,
    AssignmentTask,
    AssignmentTaskSubmission,
    AssignmentTaskTypeEnum,
    AssignmentUserSubmission,
    AssignmentUserSubmissionStatus,
    GradingTypeEnum,
)
from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.chapters import Chapter
from src.db.courses.courses import Course
from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse, MkaComplianceExpected
from src.db.mka_user_attributes import MkaUserAttributes
from src.db.resource_authors import ResourceAuthor, ResourceAuthorshipEnum, ResourceAuthorshipStatusEnum
from src.db.roles import Role, RoleTypeEnum
from src.db.trail_runs import StatusEnum, TrailRun
from src.db.trail_steps import TrailStep
from src.db.trails import Trail
from src.db.user_organizations import UserOrganization
from src.db.users import User
from src.services.mka import attributes as attr_svc
from src.tests.conftest import USER_RIGHTS

NOW = str(datetime.now())


async def add_user(db, org_id, uid, email, role_id=4, signup="google"):
    db.add(User(id=uid, username=f"u{uid}", first_name="F", last_name="L", email=email, password="x",
                user_uuid=f"user_{uid}", signup_method=signup, creation_date=NOW, update_date=NOW))
    await db.commit()
    if org_id is not None:
        db.add(UserOrganization(user_id=uid, org_id=org_id, role_id=role_id, creation_date=NOW, update_date=NOW))
        await db.commit()


async def add_attributes(db, uid, email, *, stale=False, email_seen=None, **eff):
    effective = {
        "status": "matched", "is_officeholder": True, "level": None, "department": None, "role": None,
        "role_title": None, "majlis": None, "region": None, "source": "parser", "flags": [],
    }
    effective.update(eff)
    db.add(MkaUserAttributes(
        user_id=uid, email_seen=email_seen or email.lower(), derived={}, rules_version=attr_svc.get_rules().version,
        stale=stale, effective=effective, eff_status=effective["status"], eff_level=effective["level"],
        eff_department=effective["department"], eff_role=effective["role"],
    ))
    await db.commit()


async def add_course(db, org_id, cid, uuid, name, n_published, n_unpublished=0, base=0):
    db.add(Course(id=cid, name=name, description="d", public=True, published=True, open_to_contributors=False,
                  org_id=org_id, course_uuid=uuid, creation_date=NOW, update_date=NOW))
    db.add(Chapter(id=cid, name="Ch", description="d", org_id=org_id, course_id=cid, chapter_uuid=f"chapter_{cid}",
                   creation_date=NOW, update_date=NOW))
    await db.commit()
    ids = []
    for i in range(n_published + n_unpublished):
        aid = base + i + 1
        published = i < n_published
        await add_activity(db, org_id, cid, aid, published)
        ids.append(aid)
    return ids


async def add_activity(db, org_id, cid, aid, published=True, assignment=False):
    db.add(Activity(
        id=aid, name=f"act{aid}", activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
        activity_sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE, content={}, published=published,
        org_id=org_id, course_id=cid, activity_uuid=f"activity_{aid}", creation_date=NOW, update_date=NOW))
    db.add(ChapterActivity(order=aid, chapter_id=cid, activity_id=aid, course_id=cid, org_id=org_id,
                           creation_date=NOW, update_date=NOW))
    await db.commit()


async def add_assignment(db, org_id, cid, aid_activity, asg_id):
    await add_activity(db, org_id, cid, aid_activity, True)
    db.add(Assignment(id=asg_id, title="t", description="d", grading_type=GradingTypeEnum.PERCENTAGE,
                      org_id=org_id, course_id=cid, chapter_id=cid, activity_id=aid_activity,
                      assignment_uuid=f"assignment_{asg_id}", creation_date=NOW, update_date=NOW))
    await db.commit()


def quiz_contents(majlis_names):
    return {"questions": [{"questionUUID": "q-majlis", "questionText": "Which Majlis do you serve in?",
                           "options": [{"optionUUID": f"o-{m}", "text": m, "assigned_right_answer": False}
                                       for m in majlis_names]}]}


FORM_CONTENTS = {"questions": [
    {"questionUUID": "q-rq", "questionText": "Name of your Regional Qaid",
     "blanks": [{"blankUUID": "b-rq", "placeholder": "Regional Qaid", "correctAnswer": ""}]},
    {"questionUUID": "q-head", "questionText": "Name of the National Mohtamim Tabligh",
     "blanks": [{"blankUUID": "b-head", "placeholder": "Department head", "correctAnswer": ""}]},
]}


async def add_tasks(db, org_id, cid, asg_id):
    db.add(AssignmentTask(id=asg_id * 10 + 1, title="m", description="d", hint="h",
                          assignment_type=AssignmentTaskTypeEnum.QUIZ, contents=quiz_contents(["Albany", "Boston"]),
                          assignment_id=asg_id, org_id=org_id, course_id=cid, chapter_id=cid, activity_id=1,
                          assignment_task_uuid=f"assignmenttask_{asg_id}1", creation_date=NOW, update_date=NOW))
    db.add(AssignmentTask(id=asg_id * 10 + 2, title="c", description="d", hint="h",
                          assignment_type=AssignmentTaskTypeEnum.FORM, contents=FORM_CONTENTS,
                          assignment_id=asg_id, org_id=org_id, course_id=cid, chapter_id=cid, activity_id=1,
                          assignment_task_uuid=f"assignmenttask_{asg_id}2", creation_date=NOW, update_date=NOW))
    await db.commit()


async def add_contact_answers(db, uid, asg_id, cid, majlis, rq, head):
    quiz = {"submissions": [{"questionUUID": "q-majlis", "optionUUID": f"o-{m}", "answer": m == majlis}
                            for m in ("Albany", "Boston")]}
    form = {"submissions": [{"questionUUID": "q-rq", "blankUUID": "b-rq", "answer": rq},
                            {"questionUUID": "q-head", "blankUUID": "b-head", "answer": head}]}
    for tid, typ, payload in ((asg_id * 10 + 1, AssignmentTaskTypeEnum.QUIZ, quiz), (asg_id * 10 + 2, AssignmentTaskTypeEnum.FORM, form)):
        db.add(AssignmentTaskSubmission(
            assignment_task_submission_uuid=f"ats_{uid}_{tid}", task_submission=payload, grade=0,
            task_submission_grade_feedback="", assignment_type=typ, user_id=uid, activity_id=1, course_id=cid,
            chapter_id=cid, assignment_task_id=tid, creation_date=NOW, update_date=NOW))
    await db.commit()


async def progress(db, org_id, uid, cid, activity_ids, day, status=StatusEnum.STATUS_IN_PROGRESS):
    trail = (await db.execute(select(Trail).where(Trail.user_id == uid, Trail.org_id == org_id))).scalars().first()
    if trail is None:
        trail = Trail(user_id=uid, org_id=org_id, trail_uuid=f"trail_{uid}", creation_date=NOW, update_date=NOW)
        db.add(trail)
        await db.commit()
        await db.refresh(trail)
    run = TrailRun(trail_id=trail.id, course_id=cid, org_id=org_id, user_id=uid, status=status,
                   creation_date=NOW, update_date=NOW)
    db.add(run)
    await db.commit()
    await db.refresh(run)
    for aid in activity_ids:
        db.add(TrailStep(complete=True, teacher_verified=False, grade="", data={}, trailrun_id=run.id,
                         trail_id=trail.id, activity_id=aid, course_id=cid, org_id=org_id, user_id=uid,
                         creation_date=f"{day} 10:00:00.000000", update_date=f"{day} 10:00:00.000000"))
    await db.commit()


async def attest(db, uid, asg_id, day, status=AssignmentUserSubmissionStatus.SUBMITTED):
    db.add(AssignmentUserSubmission(
        user_id=uid, assignment_id=asg_id, grade=0, submission_status=status, attempt_number=1,
        creation_date=f"{day} 11:00:00.000000", update_date=f"{day} 11:00:00.000000",
        assignmentusersubmission_uuid=f"aus_{uid}_{asg_id}"))
    await db.commit()


def expected(org_id, cycle_id, email, dept, level, majlis=None, region=None, role="", name=None, **kw):
    return MkaComplianceExpected(org_id=org_id, cycle_id=cycle_id, email=email, department=dept, level=level,
                                 majlis=majlis, region=region, role_title=role, person_name=name, **kw)


async def build_world(db, org, other_org, admin_user, regular_user):
    w = SimpleNamespace(org=org, other_org=other_org)

    # roles ------------------------------------------------------------------------------------------------
    rights = USER_RIGHTS.model_dump()
    rights["organizations"]["action_update"] = True
    db.add(Role(id=5, name="Org editor", org_id=org.id, role_type=RoleTypeEnum.TYPE_ORGANIZATION,
                role_uuid="role_orged", rights=rights, creation_date=NOW, update_date=NOW))
    await db.commit()

    # org 1 people -------------------------------------------------------------------------------------------
    people = {
        20: ("maint@example.invalid", 2), 21: ("orged@example.invalid", 5), 22: ("nat.aitmad@example.invalid", 4),
        23: ("author.t@example.invalid", 4), 24: ("inactive.t@example.invalid", 4),
        25: ("local.sadr@example.invalid", 4), 26: ("stale.nat@example.invalid", 4),
        27: ("reporter.t@example.invalid", 4), 28: ("author.g@example.invalid", 4),
        31: ("l1@example.invalid", 4), 32: ("l2@example.invalid", 4), 33: ("l3@example.invalid", 4),
        34: ("l4@example.invalid", 4), 35: ("ex@example.invalid", 4),
    }
    for uid, (email, role) in people.items():
        await add_user(db, org.id, uid, email, role)
    await add_attributes(db, 22, "nat.aitmad@example.invalid", level="national", department="aitmad", role="mohtamim")
    await add_attributes(db, 25, "local.sadr@example.invalid", level="local", role="sadr", majlis="Albany", region="Northeast")
    await add_attributes(db, 26, "stale.nat@example.invalid", stale=True, level="national", department="aitmad")

    # org 2 people (+ the cross-tenant email twin) -------------------------------------------------------------
    await add_user(db, other_org.id, 40, "admin2@example.invalid", 1)
    await add_user(db, other_org.id, 41, "o2.l1@example.invalid", 4)
    await add_user(db, other_org.id, 42, "crossorg@example.invalid", 4)  # on org 1's roster, member of org 2 only

    # org 1 courses ----------------------------------------------------------------------------------------
    await add_course(db, org.id, 101, "course_general", "General 2026-27", 3, 1, base=1000)          # acts 1001-1004
    await add_assignment(db, org.id, 101, 1005, 5001)
    await add_course(db, org.id, 102, "course_tabligh", "Tabligh 2026-27", 2, 1, base=1010)         # 1011-1013
    await add_assignment(db, org.id, 102, 1015, 5002)
    await add_assignment(db, org.id, 102, 1016, 5003)
    await add_tasks(db, org.id, 102, 5003)
    await add_course(db, org.id, 103, "course_maal", "Maal 2026-27", 2, 0, base=1020)               # 1021-1022
    await add_assignment(db, org.id, 103, 1025, 5004)
    # org 2 course
    await add_course(db, other_org.id, 201, "course_o2_general", "Other general", 2, 0, base=2000)
    await add_assignment(db, other_org.id, 201, 2005, 6001)

    # cycles ----------------------------------------------------------------------------------------------
    c1 = MkaComplianceCycle(org_id=org.id, label="2026-27", starts_on=date(2026, 11, 1), deadline_on=date(2026, 12, 1))
    c2 = MkaComplianceCycle(org_id=other_org.id, label="2026-27", starts_on=date(2026, 11, 1), deadline_on=date(2026, 12, 1))
    db.add(c1)
    db.add(c2)
    await db.commit()
    w.cycle, w.cycle2 = c1, c2
    for cid, uuid, kind, dept, so, cc in (
        (101, "course_general", "general", None, 5001, None),
        (102, "course_tabligh", "department", "tabligh", 5002, 5003),
        (103, "course_maal", "department", "maal", 5004, None),
    ):
        db.add(MkaComplianceCycleCourse(org_id=org.id, cycle_id=c1.id, course_id=cid, course_uuid=uuid, kind=kind,
                                        department=dept, signoff_assignment_id=so, contact_check_assignment_id=cc))
    db.add(MkaComplianceCycleCourse(org_id=other_org.id, cycle_id=c2.id, course_id=201, course_uuid="course_o2_general",
                                    kind="general", signoff_assignment_id=6001))
    await db.commit()

    # rosters ---------------------------------------------------------------------------------------------
    o = org.id
    for row in (
        expected(o, c1.id, "l1@example.invalid", "tabligh", "local", "Albany", "Northeast", "Nazim Tabligh", "L One"),
        expected(o, c1.id, "l2@example.invalid", "tabligh", "local", "Boston", "Northeast", "Nazim Tabligh", "L Two"),
        expected(o, c1.id, "l3@example.invalid", "maal", "local", "Albany", "Northeast", "Nazim Maal", "L Three"),
        expected(o, c1.id, "l4@example.invalid", "maal", "local", "Syracuse", "Northeast", "Nazim Maal", "L Four"),
        expected(o, c1.id, "ghost1@example.invalid", "tabligh", "local", "Dallas", "Southwest", "Nazim Tabligh", "=HYPERLINK(\"http://evil.invalid\",\"x\")"),
        expected(o, c1.id, "ghost2@example.invalid", "maal", "regional", None, "Southwest", "Regional Nazim Maal", "Ghost Two"),
        expected(o, c1.id, "crossorg@example.invalid", "tabligh", "local", "Albany", "Northeast", "Nazim Tabligh", "Cross Org"),
        expected(o, c1.id, "head.tabligh@example.invalid", "tabligh", "national", None, None, "Mohtamim Tabligh", "Jane Doe"),
        expected(o, c1.id, "rq.ne@example.invalid", "", "regional", None, "Northeast", "Regional Qaid", "Rob Qaid"),
        expected(o, c1.id, "ex@example.invalid", "", "national", None, None, "Sadr", "Exec One"),
    ):
        db.add(row)
    for email, uid in (("o2.l1@example.invalid", 41), ("crossorg@example.invalid", 42), ("nobody2@example.invalid", None)):
        db.add(expected(other_org.id, c2.id, email, "", "national", None, None, "Sadr", "O2"))
    await db.commit()

    # progress (org 1) ---------------------------------------------------------------------------------------
    await progress(db, o, 31, 101, [1001, 1002, 1003], "2026-11-03", StatusEnum.STATUS_COMPLETED)
    await progress(db, o, 31, 102, [1011, 1012], "2026-11-05", StatusEnum.STATUS_COMPLETED)
    await attest(db, 31, 5001, "2026-11-06")
    await attest(db, 31, 5002, "2026-11-07")
    await add_contact_answers(db, 31, 5003, 102, "Albany", "Rob Qaid", "Jane Doe")
    await progress(db, o, 32, 101, [1001, 1002, 1003], "2026-11-08")
    await progress(db, o, 32, 102, [1011, 1012], "2026-11-09")
    await add_contact_answers(db, 32, 5003, 102, "Albany", "Somebody Else", "Jane Doe")  # 2 mismatches (Boston expected)
    await progress(db, o, 33, 101, [1001], "2026-11-10")
    await progress(db, o, 35, 101, [1001, 1002, 1003], "2026-11-04")
    await attest(db, 35, 5001, "2026-11-12")
    # org 2 progress
    await progress(db, other_org.id, 41, 201, [2001, 2002], "2026-11-03")
    await attest(db, 41, 6001, "2026-11-04")

    # authors ---------------------------------------------------------------------------------------------
    def author(uid, uuid, authorship=ResourceAuthorshipEnum.CREATOR, status=ResourceAuthorshipStatusEnum.ACTIVE):
        return ResourceAuthor(resource_uuid=uuid, user_id=uid, authorship=authorship, authorship_status=status,
                              creation_date=NOW, update_date=NOW)
    db.add(author(23, "course_tabligh"))
    db.add(author(24, "course_tabligh", status=ResourceAuthorshipStatusEnum.INACTIVE))
    db.add(author(27, "course_tabligh", authorship=ResourceAuthorshipEnum.REPORTER))
    db.add(author(28, "course_general", authorship=ResourceAuthorshipEnum.CONTRIBUTOR))
    await db.commit()
    return w
