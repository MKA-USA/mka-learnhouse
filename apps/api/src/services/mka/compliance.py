"""MKA fork: compliance read model (spec sections 3-4).

Pipeline for every read endpoint (all SET-BASED: a handful of grouped queries per request, never per user):

1. the expected roster of the cycle (``mka_compliance_expected``);
2. roster emails -> users of THIS org (``lower(email)`` join + ``userorganization``): a roster row without a match
   is ``not_signed_in``;
3. per (user, course): published-lesson totals (sign-off / contact-check assignment activities excluded), completed-step counts + dates (``trailstep`` x ``chapteractivity``
   x ``activity.published``), run status, sign-off submissions, contact-check answers;
4. pure scoring (``compliance_scoring``) over plain dict records.

Callers must have resolved the scope first (``compliance_scope``); this module only ever sees an ``org_id``,
a cycle and course rows that were already filtered to that org.

Contact self-check (FORM answers) - VERIFIED shapes (assignments.py ``_grade_form_task`` / ``_grade_quiz_task``
and the provisioner's templates/attestation.ts):
* ``assignmenttasksubmission.task_submission`` for a FORM task is ``{"submissions": [{"questionUUID",
  "blankUUID", "answer"}]}``; the task's ``contents`` is ``{"questions": [{"questionUUID", "questionText",
  "blanks": [{"blankUUID", ...}]}]}``;
* for a QUIZ task it is ``{"submissions": [{"questionUUID", "optionUUID", "answer": bool}]}`` and the options
  (text = Majlis name) live in ``contents.questions[].options[]``.
UNCONFIRMED: which roster rows count as the "regional Qaid" / "department head" (``CONTACT_CHECK_RULES``).
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import Activity
from src.db.courses.assignments import (
    Assignment,
    AssignmentTask,
    AssignmentTaskSubmission,
    AssignmentTaskTypeEnum,
    AssignmentUserSubmission,
    AssignmentUserSubmissionStatus,
)
from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.courses import Course
from src.db.mka_compliance import (
    MkaComplianceCycle,
    MkaComplianceCycleCourse,
    MkaComplianceExpected,
)
from src.db.trail_runs import TrailRun
from src.db.trail_steps import TrailStep
from src.db.user_organizations import UserOrganization
from src.db.users import User
from src.db.mka_user_attributes import MkaUserAttributes
from src.services.mka import attributes as attrs
from src.services.mka import compliance_scoring as cs

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50
MAX_CSV_ROWS = 5000
MAX_ATTENTION_ITEMS = 50

# UNCONFIRMED (owner to confirm): how the expected roster identifies the people a learner is asked to name in the
# contact self-check. Lower-case substrings of ``role_title``; a roster with no match simply cannot produce a
# mismatch for that field (never a false alarm).
CONTACT_CHECK_RULES: dict[str, dict] = {
    "regional_qaid": {"level": "regional", "role_keywords": ("regional qaid",)},
    "dept_head": {"level": "national", "role_keywords": ("mohtamim", "motamid")},
}
# How FORM questions are mapped to fields: lower-case substrings of ``questionText`` (provisioner wording:
# "Name of your Regional Qaid" / "Name of the National Mohtamim <dept>").
CONTACT_QUESTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "regional_qaid": ("regional qaid",),
    "dept_head": ("mohtamim", "motamid", "department head"),
}

SUBMITTED_STATES = (
    AssignmentUserSubmissionStatus.SUBMITTED,
    AssignmentUserSubmissionStatus.GRADED,
    AssignmentUserSubmissionStatus.LATE,
)


# The cycle's calendar. A deadline is the END of that day in this zone (default America/New_York; override with
# MKA_COMPLIANCE_TZ), so nobody turns overdue at 7pm Eastern on the deadline day.
CYCLE_TIMEZONE = os.environ.get("MKA_COMPLIANCE_TZ", "America/New_York")


def today() -> str:
    """'As of' day in the cycle timezone. Tests monkeypatch this."""
    try:
        zone = ZoneInfo(CYCLE_TIMEZONE)
    except Exception:  # unknown zone name: fall back to UTC rather than fail
        zone = timezone.utc
    return datetime.now(zone).date().isoformat()


def _day(value: Any) -> Optional[str]:
    return cs.day_str(value)


def _round1(x: float) -> float:
    return cs._round1(x)


# ---------------------------------------------------------------------------------------------------------
# loading (set-based)
# ---------------------------------------------------------------------------------------------------------

# M2/M2b: an account only counts as the officeholder when its identity is PROVEN FOR THAT EMAIL, using the attributes
# trust model: a row exists, is not stale, ``email_seen`` equals the account's CURRENT email (so changing the profile
# email to a role address breaks the match) and the Workspace proof (``verified_hd``) covers that address's domain.
# SQL narrows the candidates; ``_proven`` re-checks each with the attributes module's own ``is_stale``.
def _candidate_filter():
    return (
        MkaUserAttributes.user_id == User.id,
        MkaUserAttributes.stale.is_(False),  # type: ignore[attr-defined]
        MkaUserAttributes.email_seen == func.lower(User.email),
        MkaUserAttributes.verified_hd.is_not(None),  # type: ignore[union-attr]
    )


def _proven(row: MkaUserAttributes, user: User) -> bool:
    """Per-address Workspace proof, delegated to the attributes module (single source of truth)."""
    return attrs.is_address_proven(row, user)


def _roster_users(org_id: int, cycle_id: int):
    """SELECT id of the users of THIS org whose email is on the cycle's roster."""
    roster_emails = select(MkaComplianceExpected.email).where(
        MkaComplianceExpected.cycle_id == cycle_id, MkaComplianceExpected.org_id == org_id
    )
    return (
        select(User.id)
        .join(UserOrganization, (UserOrganization.user_id == User.id) & (UserOrganization.org_id == org_id))
        .where(func.lower(User.email).in_(roster_emails), *_candidate_filter())
    )


async def load_roster(db: AsyncSession, org_id: int, cycle_id: int) -> list[MkaComplianceExpected]:
    return list(
        (
            await db.execute(
                select(MkaComplianceExpected)
                .where(MkaComplianceExpected.cycle_id == cycle_id, MkaComplianceExpected.org_id == org_id)
                .order_by(MkaComplianceExpected.id)  # type: ignore[arg-type]
            )
        ).scalars().all()
    )


async def load_user_map(db: AsyncSession, org_id: int, cycle_id: int) -> dict[str, int]:
    """lower(email) -> user id, restricted to roster emails and members of the org."""
    roster_emails = select(MkaComplianceExpected.email).where(
        MkaComplianceExpected.cycle_id == cycle_id, MkaComplianceExpected.org_id == org_id
    )
    rows = (
        await db.execute(
            select(User, MkaUserAttributes)
            .join(UserOrganization, (UserOrganization.user_id == User.id) & (UserOrganization.org_id == org_id))
            .where(func.lower(User.email).in_(roster_emails), *_candidate_filter())
            .order_by(User.id)
        )
    ).all()
    out: dict[str, int] = {}
    for user, row in rows:
        if _proven(row, user):
            out.setdefault(attrs.normalize_email(user.email), user.id)  # deterministic if two accounts ever share an email
    return out


async def load_progress(
    db: AsyncSession, org_id: int, cycle: MkaComplianceCycle, links: list[MkaComplianceCycleCourse]
) -> dict:
    """Progress for the given cycle courses. Returns::

        {"totals": {course_id: n_published_lessons},
         "progress": {(user_id, course_id): course-progress dict (see compliance_scoring)},
         "contact": {(user_id, assignment_id): {"answers": {...}} },
         "contact_tasks": {assignment_id: [tasks]}}
    """
    course_ids = sorted({cc.course_id for cc in links})
    if not course_ids:
        return {"totals": {}, "progress": {}, "contact": {}}
    roster_users = _roster_users(org_id, cycle.id)  # type: ignore[arg-type]

    # The sign-off and contact-check assignments are the attestation, NOT lessons: counting their activities would
    # make `completed` (all lessons done, not yet attested) impossible. Deviation from the literal spec wording,
    # documented in the module docstring and the report.
    assignment_ids = sorted(
        {a for cc in links for a in (cc.signoff_assignment_id, cc.contact_check_assignment_id) if a}
    )
    excluded_activities: list[int] = []
    if assignment_ids:
        excluded_activities = [
            aid for (aid,) in (
                await db.execute(
                    select(Assignment.activity_id).where(
                        Assignment.id.in_(assignment_ids), Assignment.org_id == org_id  # type: ignore[attr-defined]
                    )
                )
            ).all()
        ]
    lesson_filter = [Activity.id.not_in(excluded_activities)] if excluded_activities else []  # type: ignore[attr-defined]

    totals = {
        cid: n
        for cid, n in (
            await db.execute(
                select(ChapterActivity.course_id, func.count(distinct(ChapterActivity.activity_id)))
                .join(Activity, Activity.id == ChapterActivity.activity_id)
                .where(
                    ChapterActivity.course_id.in_(course_ids),  # type: ignore[attr-defined]
                    ChapterActivity.org_id == org_id,
                    Activity.published.is_(True),  # type: ignore[attr-defined]
                    *lesson_filter,
                )
                .group_by(ChapterActivity.course_id)
            )
        ).all()
    }

    done_rows = (
        await db.execute(
            select(
                TrailStep.user_id, TrailStep.course_id,
                func.count(distinct(TrailStep.activity_id)), func.max(TrailStep.creation_date),
            )
            .join(
                ChapterActivity,
                (ChapterActivity.activity_id == TrailStep.activity_id) & (ChapterActivity.course_id == TrailStep.course_id),
            )
            .join(Activity, Activity.id == TrailStep.activity_id)
            .where(
                TrailStep.complete.is_(True),  # type: ignore[attr-defined]
                Activity.published.is_(True),  # type: ignore[attr-defined]
                TrailStep.course_id.in_(course_ids),  # type: ignore[attr-defined]
                TrailStep.org_id == org_id,
                TrailStep.user_id.in_(roster_users),  # type: ignore[attr-defined]
                *lesson_filter,
            )
            .group_by(TrailStep.user_id, TrailStep.course_id)
        )
    ).all()

    run_rows = (
        await db.execute(
            select(TrailRun.user_id, TrailRun.course_id, TrailRun.status)
            .where(
                TrailRun.course_id.in_(course_ids),  # type: ignore[attr-defined]
                TrailRun.org_id == org_id,
                TrailRun.user_id.in_(roster_users),  # type: ignore[attr-defined]
            )
        )
    ).all()

    signoff = {cc.signoff_assignment_id: cc.course_id for cc in links if cc.signoff_assignment_id}
    attest_rows = []
    if signoff:
        attest_rows = (
            await db.execute(
                select(AssignmentUserSubmission.user_id, AssignmentUserSubmission.assignment_id, AssignmentUserSubmission.creation_date)
                .join(Assignment, Assignment.id == AssignmentUserSubmission.assignment_id)
                .where(
                    AssignmentUserSubmission.assignment_id.in_(list(signoff)),  # type: ignore[attr-defined]
                    Assignment.org_id == org_id,
                    AssignmentUserSubmission.submission_status.in_(SUBMITTED_STATES),  # type: ignore[attr-defined]
                    AssignmentUserSubmission.user_id.in_(roster_users),  # type: ignore[attr-defined]
                )
            )
        ).all()

    progress: dict[tuple[int, int], dict] = {}

    def slot(uid: int, cid: int) -> dict:
        return progress.setdefault((uid, cid), {
            "enrolled": False, "lessons_done": 0, "lessons_total": totals.get(cid, 0), "completed_at": None,
            "attested_at": None, "last_activity_at": None, "trailrun_status": None,
        })

    for uid, cid, n_done, last in done_rows:
        p = slot(uid, cid)
        p["enrolled"] = True
        p["lessons_done"] = n_done
        p["last_activity_at"] = _day(last)
        total = totals.get(cid, 0)
        if total > 0 and n_done >= total:
            p["completed_at"] = _day(last)
    for uid, cid, run_status in run_rows:
        p = slot(uid, cid)
        p["enrolled"] = True
        p["trailrun_status"] = getattr(run_status, "value", run_status)
    for uid, aid, created in attest_rows:
        p = slot(uid, signoff[aid])
        p["enrolled"] = True
        p["attested_at"] = _day(created)
        p["last_activity_at"] = cs.max_day(p["last_activity_at"], created)

    contact, contact_tasks = await _load_contact(db, org_id, links, roster_users)
    return {"totals": totals, "progress": progress, "contact": contact, "contact_tasks": contact_tasks}


async def _load_contact(db: AsyncSession, org_id: int, links, roster_users):
    ids = sorted({cc.contact_check_assignment_id for cc in links if cc.contact_check_assignment_id})
    if not ids:
        return {}, {}
    tasks = (
        await db.execute(
            select(AssignmentTask).where(
                AssignmentTask.assignment_id.in_(ids), AssignmentTask.org_id == org_id  # type: ignore[attr-defined]
            )
        )
    ).scalars().all()
    by_assignment: dict[int, list[AssignmentTask]] = {}
    for t in tasks:
        by_assignment.setdefault(t.assignment_id, []).append(t)
    task_ids = [t.id for t in tasks]
    task_assignment = {t.id: t.assignment_id for t in tasks}
    subs: dict[tuple[int, int], dict[int, dict]] = {}
    if task_ids:
        for uid, task_id, payload in (
            await db.execute(
                select(AssignmentTaskSubmission.user_id, AssignmentTaskSubmission.assignment_task_id, AssignmentTaskSubmission.task_submission)
                .where(
                    AssignmentTaskSubmission.assignment_task_id.in_(task_ids),  # type: ignore[attr-defined]
                    AssignmentTaskSubmission.user_id.in_(roster_users),  # type: ignore[attr-defined]
                )
            )
        ).all():
            subs.setdefault((uid, task_assignment[task_id]), {})[task_id] = payload or {}
    contact: dict[tuple[int, int], dict] = {}
    for (uid, aid), per_task in subs.items():
        contact[(uid, aid)] = extract_contact_answers(by_assignment.get(aid, []), per_task)
    return contact, by_assignment


# ---------------------------------------------------------------------------------------------------------
# contact self-check
# ---------------------------------------------------------------------------------------------------------

def classify_question(text: str) -> Optional[str]:
    t = (text or "").lower()
    for field_name, words in CONTACT_QUESTION_KEYWORDS.items():
        if any(w in t for w in words):
            return field_name
    return None


def extract_contact_answers(tasks: list, submissions_by_task: dict[int, dict]) -> dict:
    """Map raw task submissions to ``{majlis, regional_qaid, dept_head}`` (missing = None). Pure; tolerant of any
    unexpected shape (never raises)."""
    answers: dict[str, Optional[str]] = {"majlis": None, "regional_qaid": None, "dept_head": None}
    for task in tasks:
        payload = submissions_by_task.get(task.id)
        contents = task.contents if isinstance(task.contents, dict) else {}
        subs = (payload or {}).get("submissions") if isinstance(payload, dict) else None
        if not isinstance(subs, list):
            continue
        type_ = getattr(task.assignment_type, "value", task.assignment_type)
        questions = [q for q in (contents.get("questions") or []) if isinstance(q, dict)]
        if type_ == AssignmentTaskTypeEnum.QUIZ.value:
            chosen = {s.get("optionUUID") for s in subs if isinstance(s, dict) and s.get("answer")}
            for q in questions:
                for opt in q.get("options") or []:
                    if isinstance(opt, dict) and opt.get("optionUUID") in chosen and isinstance(opt.get("text"), str):
                        answers["majlis"] = opt["text"].strip() or None
        elif type_ == AssignmentTaskTypeEnum.FORM.value:
            by_blank = {
                s.get("blankUUID"): s.get("answer") for s in subs if isinstance(s, dict) and s.get("blankUUID")
            }
            for q in questions:
                field_name = classify_question(str(q.get("questionText") or ""))
                if field_name is None:
                    continue
                for blank in q.get("blanks") or []:
                    value = by_blank.get(blank.get("blankUUID")) if isinstance(blank, dict) else None
                    if isinstance(value, str) and value.strip():
                        answers[field_name] = value.strip()
    return answers


def expected_contacts(roster: list[MkaComplianceExpected]) -> dict:
    """Index of who a learner should name, built from the roster (see CONTACT_CHECK_RULES)."""
    index: dict[str, dict[str, list[str]]] = {"regional_qaid": {}, "dept_head": {}}
    for row in roster:
        if not row.person_name:
            continue
        title = (row.role_title or "").lower()
        rule = CONTACT_CHECK_RULES["regional_qaid"]
        if row.level == rule["level"] and any(k in title for k in rule["role_keywords"]) and row.region:
            index["regional_qaid"].setdefault(row.region, []).append(row.person_name)
        rule = CONTACT_CHECK_RULES["dept_head"]
        if row.level == rule["level"] and any(k in title for k in rule["role_keywords"]):
            index["dept_head"].setdefault(row.department, []).append(row.person_name)
    return index


def self_check_for(row: MkaComplianceExpected, answers: Optional[dict], contacts: dict) -> dict:
    expected: dict[str, Any] = {}
    if row.level == "local" and row.majlis:
        expected["majlis"] = row.majlis
    if row.region and contacts["regional_qaid"].get(row.region):
        expected["regional_qaid"] = contacts["regional_qaid"][row.region]
    if row.department and contacts["dept_head"].get(row.department):
        expected["dept_head"] = contacts["dept_head"][row.department]
    return cs.evaluate_self_check(answers, expected)


# ---------------------------------------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------------------------------------

def _iso(d) -> Optional[str]:
    return d.isoformat() if d else None


class Dataset:
    """Everything the builders need, loaded once per request."""

    def __init__(self, cycle: MkaComplianceCycle, roster, user_map, progress_bundle, links, courses):
        self.cycle = cycle
        self.cycle_dict = {
            "label": cycle.label, "starts_on": cycle.starts_on.isoformat(), "deadline_on": cycle.deadline_on.isoformat(),
        }
        self.roster = roster
        self.user_map = user_map
        self.progress = progress_bundle["progress"]
        self.totals = progress_bundle["totals"]
        self.contact = progress_bundle["contact"]
        self.links = links
        self.courses = courses  # course_id -> Course
        self.contacts = expected_contacts(roster)

    def course_progress(self, uid: Optional[int], link: Optional[MkaComplianceCycleCourse]) -> Optional[dict]:
        if uid is None or link is None:
            return None
        p = self.progress.get((uid, link.course_id))
        if p is None:
            return {
                "enrolled": False, "lessons_done": 0, "lessons_total": self.totals.get(link.course_id, 0),
                "completed_at": None, "attested_at": None, "last_activity_at": None, "trailrun_status": None,
            }
        return p

    def contact_answers(self, uid: Optional[int], link: Optional[MkaComplianceCycleCourse]) -> Optional[dict]:
        if uid is None or link is None or not link.contact_check_assignment_id:
            return None
        return self.contact.get((uid, link.contact_check_assignment_id))


async def load_dataset(
    db: AsyncSession, org_id: int, cycle: MkaComplianceCycle, links: list, courses: dict
) -> Dataset:
    roster = await load_roster(db, org_id, cycle.id)  # type: ignore[arg-type]
    user_map = await load_user_map(db, org_id, cycle.id) if roster else {}
    bundle = await load_progress(db, org_id, cycle, links) if roster else {"progress": {}, "totals": {}, "contact": {}}
    return Dataset(cycle, roster, user_map, bundle, links, courses)


def dedupe(rows: list[dict], key) -> list[dict]:
    """M1: one record per distinct key (first roster row wins); the role titles of the merged rows are joined so
    nothing is lost. Counts, percentages, RAG, lists, CSV and trend must all be per distinct person."""
    seen: dict[Any, dict] = {}
    for r in rows:
        k = key(r)
        if k not in seen:
            seen[k] = {**r, "role_titles": [r["role_title"]] if r["role_title"] else []}
            continue
        first = seen[k]
        if r["role_title"] and r["role_title"] not in first["role_titles"]:
            first["role_titles"].append(r["role_title"])
    out = list(seen.values())
    for r in out:
        r["role_title"] = " / ".join(r["role_titles"])
    return out


def person_records(ds: Dataset, as_of: str, cfg: Optional[dict] = None) -> list[dict]:
    """One scored record per roster row across ALL cycle courses (general + the row's department course)."""
    general = next((cc for cc in ds.links if cc.kind == "general"), None)
    dept_links = {cc.department: cc for cc in ds.links if cc.kind == "department" and cc.department}
    out = []
    for row in ds.roster:
        uid = ds.user_map.get(row.email)
        dept_link = dept_links.get(row.department) if row.department else None
        merged: Optional[dict] = None
        for link in (general, dept_link):
            answers = ds.contact_answers(uid, link)
            if answers is not None:
                res = self_check_for(row, answers, ds.contacts)
                merged = merged or {"answered": False, "mismatches": []}
                merged["answered"] = merged["answered"] or res["answered"]
                merged["mismatches"] = sorted(set(merged["mismatches"]) | set(res["mismatches"]))
        record = {
            "id": row.id, "email": row.email, "person_name": row.person_name, "department_slug": row.department,
            "level": row.level, "region": row.region or "", "majlis": row.majlis or "", "role_title": row.role_title,
            "appointed_on": _iso(row.appointed_on), "signed_in": uid is not None,
            "general": ds.course_progress(uid, general), "dept_course": ds.course_progress(uid, dept_link),
            "dept_required": dept_link is not None, "general_required": general is not None,
            "self_check": merged,
        }
        out.append(cs.score_learner(record, ds.cycle_dict, as_of, cfg))
    return out


def course_records(ds: Dataset, link: MkaComplianceCycleCourse, as_of: str, cfg: Optional[dict] = None) -> list[dict]:
    """One scored record per roster row relevant to ONE course (the course's progress sits in the 'general' slot, so
    the per-course status is: not_signed_in / not_started / in_progress / completed / attested, plus overdue)."""
    out = []
    for row in ds.roster:
        if link.kind == "department" and row.department != link.department:
            continue
        uid = ds.user_map.get(row.email)
        prog = ds.course_progress(uid, link)
        answers = ds.contact_answers(uid, link)
        sc = self_check_for(row, answers, ds.contacts) if link.contact_check_assignment_id else None
        record = {
            "id": row.id, "email": row.email, "person_name": row.person_name, "department_slug": "",
            "level": row.level, "region": row.region or "", "majlis": row.majlis or "", "role_title": row.role_title,
            "appointed_on": _iso(row.appointed_on), "signed_in": uid is not None, "general": prog,
            "dept_course": None, "self_check": sc,
        }
        scored = cs.score_learner(record, ds.cycle_dict, as_of, cfg)
        scored["department_slug"] = row.department  # real department for display/filters
        scored["signed_in"] = uid is not None
        scored["lessons_total"] = ds.totals.get(link.course_id, 0)  # the course's size, even for people not enrolled
        scored["lessons_done"] = prog["lessons_done"] if prog else 0
        scored["trailrun_status"] = prog.get("trailrun_status") if prog else None
        scored["contact_check"] = _contact_view(link, answers, sc)
        out.append(scored)
    return dedupe(out, lambda r: r["email"])


def _contact_view(link, answers, sc) -> dict:
    if not link.contact_check_assignment_id:
        return {"answers": None, "mismatch": None}
    if sc is None or not sc["answered"]:
        return {"answers": answers, "mismatch": None}
    return {"answers": answers, "mismatch": bool(sc["mismatches"]), "mismatch_fields": sc["mismatches"]}


# ---------------------------------------------------------------------------------------------------------
# presentation
# ---------------------------------------------------------------------------------------------------------

def _pct(x: float) -> float:
    return _round1(x * 100)


def public_group(agg: dict, att: dict) -> dict:
    """Counts + rates (percent values are 0..100) + RAG for one group."""
    return {
        "expected": agg["expected"],
        "not_signed_in": agg["not_signed_in"], "not_started": agg["not_started"],
        "in_progress": agg["in_progress"], "completed": agg["completed"], "attested": agg["attested"],
        "overdue": agg["overdue"],
        "started_pct": _pct(agg["started_pct"]), "completed_pct": _pct(agg["completed_pct"]),
        "attested_pct": _pct(agg["attested_pct"]), "expected_attested_pct": _pct(agg["expected_attested_pct"]),
        "median_days_to_complete": agg["median_days_to_complete"],
        "last_activity_at": agg["last_activity_at"],
        "contact_mismatches": agg["self_check_mismatches"],
        "rag": att["rag"], "score": att["score"], "reasons": att["reasons"], "summary": att["summary"],
    }


def _totals(rows: list[dict], ds: Dataset, as_of: str, cfg: Optional[dict]):
    agg = cs.aggregate("all", rows, ds.cycle_dict)
    att = cs.attention(agg, ds.cycle_dict, as_of, cfg)
    return agg, att


def _breakdown(rows: list[dict], field_name: str, ds: Dataset, as_of: str, cfg: Optional[dict], keep_empty: bool = False) -> list[dict]:
    out = []
    for key, group in sorted(cs.group_by(rows, field_name).items()):
        agg = cs.aggregate(key, group, ds.cycle_dict)
        att = cs.attention(agg, ds.cycle_dict, as_of, cfg)
        out.append({field_name: key if (key or keep_empty) else None, **public_group(agg, att)})
    return out


EXECUTIVE_SLUG = "executive"
EXECUTIVE_NAME = "National leadership"


def dept_out(slug: str) -> str:
    """API value for a department: '' (no department: executives) is reported as the stable slug 'executive'."""
    return slug or EXECUTIVE_SLUG


def dept_in(slug: Optional[str]) -> str:
    return "" if (slug or "").lower() == EXECUTIVE_SLUG else (slug or "")


def dept_name(slug: str) -> str:
    if not slug:
        return EXECUTIVE_NAME
    return attrs.get_rules().department_names.get(slug) or slug.replace("_", " ").title()


def cycle_view(cycle: Optional[MkaComplianceCycle]) -> Optional[dict]:
    if cycle is None:
        return None
    return {
        "id": cycle.id, "label": cycle.label,
        "starts_on": cycle.starts_on.isoformat(), "deadline_on": cycle.deadline_on.isoformat(),
    }


def course_view(link: MkaComplianceCycleCourse, course: Course) -> dict:
    return {
        "course_uuid": link.course_uuid, "name": course.name, "kind": link.kind, "department": link.department,
        "department_name": dept_name(link.department) if link.department else None,
    }


ATTENTION_KEYS = ("rag", "score", "reasons", "expected", "attested", "attested_pct", "overdue", "not_signed_in", "not_started")

EMPTY_TOTALS = {
    "expected": 0, "not_signed_in": 0, "not_started": 0, "in_progress": 0, "completed": 0, "attested": 0, "overdue": 0,
}


def build_overview(ds: Optional[Dataset], cycle: Optional[MkaComplianceCycle], as_of: str, cfg: Optional[dict] = None) -> dict:
    if ds is None or cycle is None:
        return {"cycle": cycle_view(cycle), "as_of": as_of, "totals": dict(EMPTY_TOTALS),
                "departments": [], "cells": [], "attention": []}
    all_rows = person_records(ds, as_of, cfg)
    rows = dedupe(all_rows, lambda r: r["email"])                      # totals: distinct people
    by_dept_rows = dedupe(all_rows, lambda r: (r["email"], r["department_slug"]))  # a person in 2 departments counts in each
    by_cell_rows = dedupe(all_rows, lambda r: (r["email"], r["department_slug"], r["region"]))
    agg, att = _totals(rows, ds, as_of, cfg)
    totals = {k: public_group(agg, att)[k] for k in EMPTY_TOTALS}
    departments = _breakdown(by_dept_rows, "department_slug", ds, as_of, cfg, keep_empty=True)
    for d in departments:
        d["department_name"] = dept_name(d["department_slug"])
        d["department"] = dept_out(d.pop("department_slug"))
    cells = []
    for key, cell_agg in cs.cross_tab(by_cell_rows, "department_slug", "region", ds.cycle_dict).items():
        dept, region = key.split(cs.CELL_SEP, 1)
        cells.append({"department": dept_out(dept), "department_name": dept_name(dept), "region": region or None,
                      **public_group(cell_agg, cs.attention(cell_agg, ds.cycle_dict, as_of, cfg))})
    cells.sort(key=lambda c: (c["department"], c["region"] or ""))
    ranked = []
    for d in departments:
        ranked.append({"department": d["department"], "department_name": d["department_name"], "region": None, **{k: d[k] for k in ATTENTION_KEYS}})
    for c in cells:
        ranked.append({"department": c["department"], "department_name": c["department_name"], "region": c["region"], **{k: c[k] for k in ATTENTION_KEYS}})
    ranked = [r for r in ranked if r["rag"] in ("red", "amber")]
    ranked.sort(key=lambda r: (-cs.rag_severity(r["rag"]), -r["score"], -r["expected"], r["department"], r["region"] or ""))
    return {
        "cycle": cycle_view(cycle), "as_of": as_of, "totals": totals, "totals_detail": public_group(agg, att),
        "departments": departments, "cells": cells, "attention": ranked[:MAX_ATTENTION_ITEMS],
    }


def build_summary(ds: Dataset, link: MkaComplianceCycleCourse, course: Course, as_of: str, cfg: Optional[dict] = None) -> dict:
    rows = course_records(ds, link, as_of, cfg)
    agg, att = _totals(rows, ds, as_of, cfg)
    detail = public_group(agg, att)
    return {
        "cycle": cycle_view(ds.cycle), "as_of": as_of,
        "course": course_view(link, course), "lessons_total": ds.totals.get(link.course_id, 0),
        "totals": {k: detail[k] for k in EMPTY_TOTALS},
        "by_region": _breakdown(rows, "region", ds, as_of, cfg),
        "by_majlis": _breakdown(rows, "majlis", ds, as_of, cfg),
        "by_level": _breakdown(rows, "level", ds, as_of, cfg),
        "rag": att["rag"], "score": att["score"], "reasons": att["reasons"], "summary": att["summary"],
        "attested_pct": detail["attested_pct"], "completed_pct": detail["completed_pct"],
        "expected_attested_pct": detail["expected_attested_pct"],
    }


SORT_FIELDS = {
    "status": lambda r: (-_status_rank(r), -r["days_overdue"], r["lessons_done"] / (r["lessons_total"] or 1), r["email"]),
    "progress": lambda r: (r["lessons_done"] / (r["lessons_total"] or 1), r["email"]),
    "name": lambda r: ((r["person_name"] or "").lower(), r["email"]),
    "email": lambda r: (r["email"],),
    "department": lambda r: (r["department_slug"], r["email"]),
    "region": lambda r: (r["region"], r["majlis"], r["email"]),
    "majlis": lambda r: (r["majlis"], r["email"]),
    "role": lambda r: (r["role_title"].lower(), r["email"]),
    "lessons": lambda r: (r["lessons_done"] / (r["lessons_total"] or 1), r["email"]),
    "last_activity": lambda r: (r["last_activity_at"] or "", r["email"]),
    "due": lambda r: (r["due_on"], r["email"]),
}
_STATUS_ORDER = {"overdue": 5, "not_signed_in": 4, "not_started": 3, "in_progress": 2, "completed": 1, "attested": 0}


def _status_rank(r: dict) -> int:
    return _STATUS_ORDER.get(r["status"], 0)


def chase_order(r: dict) -> tuple:
    """Chase list order: most overdue first, then the least progress, then email."""
    return (-r["days_overdue"], r["lessons_done"] / (r["lessons_total"] or 1), r["email"])


def _csv_list(value: Optional[str]) -> Optional[set]:
    if not value:
        return None
    items = {v.strip().lower() for v in value.split(",") if v.strip()}
    return items or None


def filter_rows(
    rows: list[dict], *, status: Optional[str] = None, stage: Optional[str] = None, overdue: Optional[bool] = None,
    region: Optional[str] = None, majlis: Optional[str] = None, level: Optional[str] = None,
    department: Optional[str] = None, q: Optional[str] = None,
) -> list[dict]:
    statuses, stages = _csv_list(status), _csv_list(stage)
    regions, majlises, levels, depts = _csv_list(region), _csv_list(majlis), _csv_list(level), _csv_list(department)
    if depts and EXECUTIVE_SLUG in depts:
        depts = (depts - {EXECUTIVE_SLUG}) | {""}
    needle = (q or "").strip().lower()
    out = []
    for r in rows:
        if statuses and r["status"] not in statuses:
            continue
        if stages and r["stage"] not in stages:
            continue
        if overdue is not None and r["overdue"] != overdue:
            continue
        if regions and r["region"].lower() not in regions:
            continue
        if majlises and r["majlis"].lower() not in majlises:
            continue
        if levels and (r["level"] or "").lower() not in levels:
            continue
        if depts and r["department_slug"].lower() not in depts:
            continue
        if needle and needle not in " ".join(
            [r["email"], r["person_name"] or "", r["majlis"], r["region"], r["role_title"]]
        ).lower():
            continue
        out.append(r)
    return out


def learner_item(r: dict) -> dict:
    return {
        "id": r["roster_id"], "email": r["email"], "role_title": r["role_title"] or None, "role_titles": r["role_titles"],
        "person_name": r["person_name"], "department": dept_out(r["department_slug"]),
        "department_name": dept_name(r["department_slug"]), "level": r["level"],
        "majlis": r["majlis"] or None, "region": r["region"] or None,
        "signed_in": r["signed_in"], "status": r["status"], "stage": r["stage"], "overdue": r["overdue"],
        "lessons_done": r["lessons_done"], "lessons_total": r["lessons_total"],
        "last_activity_at": r["last_activity_at"], "attested_at": r["attested_at"],
        "completed_at": r["completed_at"], "due_on": r["due_on"], "days_overdue": r["days_overdue"],
        "trailrun_status": r["trailrun_status"], "contact_check": r["contact_check"],
    }


def build_learners(
    ds: Dataset, link: MkaComplianceCycleCourse, course: Course, as_of: str, *, filters: dict,
    sort: Optional[str], page: int, page_size: int, cfg: Optional[dict] = None,
) -> dict:
    rows = filter_rows(course_records(ds, link, as_of, cfg), **filters)
    desc = bool(sort and sort.startswith("-"))
    key_name = (sort or "").lstrip("-") if sort else ""
    if key_name not in SORT_FIELDS:
        key_name, desc = "status", False  # default: worst / most urgent first
    rows.sort(key=SORT_FIELDS[key_name], reverse=desc)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    page = max(1, page)
    start = (page - 1) * page_size
    return {
        "cycle": cycle_view(ds.cycle), "as_of": as_of, "course": course_view(link, course),
        "items": [learner_item(r) for r in rows[start:start + page_size]],
        "total": len(rows), "page": page, "page_size": page_size,
    }


CHASE_HEADERS = (
    "Department", "Role", "Level", "Region", "Majlis", "Name", "Mailbox", "Status",
    "Lessons done", "Lessons total", "Due on", "Days overdue", "Last activity",
)


def build_chase_csv(ds: Dataset, link: MkaComplianceCycleCourse, as_of: str, *, filters: dict, cfg: Optional[dict] = None) -> tuple[str, bool]:
    """CSV of everyone in scope who is not attested (after the filters), most overdue first. Cells are
    formula-injection safe. Returns (text, truncated)."""
    rows = [r for r in filter_rows(course_records(ds, link, as_of, cfg), **filters) if r["stage"] != "attested"]
    rows.sort(key=chase_order)
    truncated = len(rows) > MAX_CSV_ROWS
    out = io.StringIO()
    out.write("\ufeff")  # UTF-8 BOM so Excel reads non-ASCII names correctly
    out.write(",".join(CHASE_HEADERS) + "\r\n")
    for r in rows[:MAX_CSV_ROWS]:
        cells = [
            dept_name(r["department_slug"]), r["role_title"], r["level"], r["region"], r["majlis"], r["person_name"], r["email"],
            r["status"], r["lessons_done"], r["lessons_total"], r["due_on"], r["days_overdue"], r["last_activity_at"],
        ]
        out.write(",".join(cs.csv_cell(c) for c in cells) + "\r\n")
    return out.getvalue(), truncated


def build_trend(ds: Dataset, link: MkaComplianceCycleCourse, course: Course, as_of: str) -> dict:
    rows = course_records(ds, link, as_of)
    series = cs.build_trend(
        [r["completed_at"] for r in rows if r["completed_at"]],
        [r["attested_at"] for r in rows if r["attested_at"]],
        len(rows), ds.cycle_dict, as_of,
    )
    return {
        "cycle": cycle_view(ds.cycle), "as_of": as_of, "course": course_view(link, course),
        "expected": len(rows), "series": series,
        "note": "Derived from TrailStep / sign-off submission creation dates (day precision, server-local time); "
                "a learner's completion day is the day of their last completed published lesson.",
    }
