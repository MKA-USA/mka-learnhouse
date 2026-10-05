"""MKA fork: server side of the audience block (contract s2): authorization, audience counts, preview-as.

Authorization (``course_author_or_admin``) mirrors ``compliance_scope._own_course_ids``: superadmin, or org admin/maintainer, or an
ACTIVE CREATOR/MAINTAINER/CONTRIBUTOR author of THIS course (which belongs to the org) who also passes the upstream ``update`` check.
API tokens are never accepted here. Everything is org-scoped by ``UserOrganization.org_id``.

Counts are aggregates only: no function here returns a name or an address except ``search_people`` (admins only) and it
returns no attributes.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from fastapi import HTTPException, Request
from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.courses import Course
from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceExpected
from src.db.mka_user_attributes import MkaUserAttributes
from src.db.organizations import Organization
from src.db.resource_authors import ResourceAuthor, ResourceAuthorshipStatusEnum
from src.db.user_organizations import UserOrganization
from src.db.users import APITokenUser, SuperadminAPITokenUser, User
from src.security.org_auth import enforce_org_mfa, get_user_org
from src.security.rbac.constants import ADMIN_OR_MAINTAINER_ROLE_IDS
from src.security.rbac.rbac import authorization_verify_based_on_roles_and_authorship
from src.security.superadmin import is_user_superadmin
from src.services.mka import attributes as attrs_svc
from src.services.mka.audience_eval import evaluate_validated, validate_rule
from src.services.mka.compliance_scope import AUTHOR_AUTHORSHIPS
from src.services.mka.identity_parser import LEVELS

MAX_PEOPLE = 20
PREVIEW_REASON = "Preview as (audience block)"
COUNTED_STATUSES = ("matched", "partial", "not_applicable")  # everything else counts as "unrecognized"


def session_uid(current_user: Any) -> int:
    """The signed-in USER's id; API-token principals (organization or superadmin) are refused."""
    if isinstance(current_user, (APITokenUser, SuperadminAPITokenUser)):
        raise HTTPException(status_code=403, detail="A user session is required")
    uid = getattr(current_user, "id", None)
    if not uid:
        raise HTTPException(status_code=403, detail="A user session is required")
    return uid


# ---------------------------------------------------------------------------------------------------------
# authorization
# ---------------------------------------------------------------------------------------------------------

async def is_course_author(request: Request, uid: int, course: Course, db: AsyncSession) -> bool:
    """ACTIVE CREATOR/MAINTAINER/CONTRIBUTOR on this course AND the upstream ``update`` check (same as the compliance scope)."""
    authored = (
        await db.execute(
            select(ResourceAuthor.id).where(
                ResourceAuthor.resource_uuid == course.course_uuid,
                ResourceAuthor.user_id == uid,
                ResourceAuthor.authorship_status == ResourceAuthorshipStatusEnum.ACTIVE,
                ResourceAuthor.authorship.in_(AUTHOR_AUTHORSHIPS),  # type: ignore[attr-defined]
            ).limit(1)
        )
    ).first()
    if authored is None:
        return False
    try:
        await authorization_verify_based_on_roles_and_authorship(request, uid, "update", course.course_uuid, db)
    except HTTPException:
        return False
    return True


async def author_can_view_all(request: Request, uid: int, course_uuid: Optional[str], db: AsyncSession) -> bool:
    """``/me?course_uuid=``: may this user see every audience section of that course? Unknown course => False (no leak)."""
    if not course_uuid:
        return False
    course = (await db.execute(select(Course).where(Course.course_uuid == course_uuid))).scalars().first()
    if course is None or await get_user_org(uid, course.org_id, db) is None:
        return False
    return await is_course_author(request, uid, course, db)


async def _member_context(current_user: Any, org_id: int, db: AsyncSession) -> tuple[int, bool, Optional[UserOrganization]]:
    """(uid, is_superadmin, membership). Superadmins need no membership but the org must exist; others must be members."""
    uid = session_uid(current_user)
    if await is_user_superadmin(uid, db):
        if await db.get(Organization, org_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        return uid, True, None
    membership = await get_user_org(uid, org_id, db)
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    await enforce_org_mfa(uid, org_id, db)
    return uid, False, membership


async def require_org_member(current_user: Any, org_id: int, db: AsyncSession) -> int:
    """``/options``: any signed-in member of the org (or a superadmin)."""
    return (await _member_context(current_user, org_id, db))[0]


async def require_org_admin(current_user: Any, org_id: int, db: AsyncSession) -> int:
    """Org admin / maintainer or superadmin ONLY (preview-as)."""
    uid, is_super, membership = await _member_context(current_user, org_id, db)
    if not is_super and membership.role_id not in ADMIN_OR_MAINTAINER_ROLE_IDS:  # type: ignore[union-attr]
        raise HTTPException(status_code=403, detail="Admin access required")
    return uid


async def course_author_or_admin(
    request: Request, current_user: Any, org_id: int, course_uuid: Optional[str], db: AsyncSession
) -> int:
    """Contract s2 authz helper: superadmin OR org admin/maintainer OR author of THIS course (in ``org_id``)."""
    uid, is_super, membership = await _member_context(current_user, org_id, db)
    if is_super or membership.role_id in ADMIN_OR_MAINTAINER_ROLE_IDS:  # type: ignore[union-attr]
        return uid
    if course_uuid:
        course = (
            await db.execute(select(Course).where(Course.course_uuid == course_uuid, Course.org_id == org_id))
        ).scalars().first()
        if course is not None and await is_course_author(request, uid, course, db):
            return uid
    raise HTTPException(status_code=403, detail="Not allowed to use the audience tools here")


# ---------------------------------------------------------------------------------------------------------
# counts
# ---------------------------------------------------------------------------------------------------------

def _expected_viewer(row: MkaComplianceExpected) -> dict:
    """A roster row as a viewer: an expected officeholder. The roster has no ``role`` (rules with a ``role`` key never match)."""
    return {
        "status": "matched", "is_officeholder": True, "level": row.level, "department": row.department or None,
        "role": None, "role_title": None, "majlis": row.majlis, "region": row.region,
    }


async def count_audience(db: AsyncSession, org_id: int, rule: dict) -> dict:
    """The ``AudienceCount`` body for an already VALIDATED rule. Aggregates only; every query is filtered by ``org_id``."""
    members = (
        await db.execute(
            select(User.id, User.email, MkaUserAttributes)
            .join(UserOrganization, UserOrganization.user_id == User.id)
            .outerjoin(MkaUserAttributes, MkaUserAttributes.user_id == User.id)
            .where(UserOrganization.org_id == org_id)
        )
    ).all()
    count = total_officeholders = unrecognized = 0
    by_level = {level: 0 for level in LEVELS}
    seen: set[int] = set()
    for uid, email, row in members:
        if uid in seen:
            continue
        seen.add(uid)
        attrs, _stale = attrs_svc.read_effective_from_row(row, SimpleNamespace(email=email))  # type: ignore[arg-type]  # fails closed
        if attrs.get("is_officeholder") is True:
            total_officeholders += 1
        if attrs.get("status") not in COUNTED_STATUSES:
            unrecognized += 1
        if evaluate_validated(rule, attrs):
            count += 1
            level = attrs.get("level")
            if attrs.get("status") in ("matched", "partial") and level in by_level:
                by_level[level] += 1

    expected = None
    cycle = (
        await db.execute(
            select(MkaComplianceCycle).where(MkaComplianceCycle.org_id == org_id)
            .order_by(MkaComplianceCycle.starts_on.desc(), MkaComplianceCycle.id.desc())  # type: ignore[attr-defined]
            .limit(1)
        )
    ).scalars().first()
    if cycle is not None:
        rows = (
            await db.execute(
                select(MkaComplianceExpected).where(
                    MkaComplianceExpected.org_id == org_id, MkaComplianceExpected.cycle_id == cycle.id
                )
            )
        ).scalars().all()
        # People, not rows: a person may hold several roster rows (one per role) and counts once; they match if ANY row does.
        people: dict[str, bool] = {}
        for r in rows:
            key = (r.email or "").strip().lower()
            people[key] = people.get(key, False) or evaluate_validated(rule, _expected_viewer(r))
        expected = {"matching": sum(people.values()), "total": len(people), "cycle_id": cycle.id}
    return {
        "count": count, "total_officeholders": total_officeholders, "unrecognized": unrecognized,
        "by_level": by_level, "expected": expected,
    }


def parse_rule_or_422(raw: Any) -> dict:
    ok, result = validate_rule(raw)
    if not ok:
        raise HTTPException(status_code=422, detail=result)
    return result


# ---------------------------------------------------------------------------------------------------------
# preview-as
# ---------------------------------------------------------------------------------------------------------

def _like_escape(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_people(db: AsyncSession, org_id: int, q: str) -> list[dict]:
    """Members of ``org_id`` whose name or email contains ``q``. No attributes. Admin routes only."""
    pattern = f"%{_like_escape(q.strip().lower())}%"
    full_name = User.first_name + " " + User.last_name  # type: ignore[operator]
    rows = (
        await db.execute(
            select(User.id, User.first_name, User.last_name, User.username, User.email)
            .join(UserOrganization, UserOrganization.user_id == User.id)
            .where(
                UserOrganization.org_id == org_id,
                or_(
                    full_name.ilike(pattern, escape="\\"),  # type: ignore[attr-defined]
                    User.email.ilike(pattern, escape="\\"),  # type: ignore[attr-defined]
                ),
            )
            .distinct()
            .order_by(User.email)  # type: ignore[arg-type]
            .limit(MAX_PEOPLE)
        )
    ).all()
    return [
        {"user_id": uid, "display_name": (f"{first or ''} {last or ''}".strip() or username or email), "email": email}
        for uid, first, last, username, email in rows
    ]


async def preview_person(db: AsyncSession, org_id: int, actor_uid: int, user_id: int) -> dict:
    """The target's EFFECTIVE (fail-closed) attributes, audited as ``preview_as``. 404 unless the target is in ``org_id``."""
    member = (
        await db.execute(
            select(UserOrganization.id).where(UserOrganization.user_id == user_id, UserOrganization.org_id == org_id).limit(1)
        )
    ).first()
    user = await db.get(User, user_id) if member is not None else None
    if user is None:
        raise HTTPException(status_code=404, detail="User not found in this organization")
    attrs, _stale = await attrs_svc.read_effective(db, user)
    attrs_svc._add_audit(db, user.id, "preview_as", None, None, actor_user_id=actor_uid, reason=PREVIEW_REASON)  # type: ignore[arg-type]
    await db.commit()
    return {"attributes": attrs}
