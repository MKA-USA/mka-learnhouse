"""Staff-only access to moderation flags (list, per-content, per-user, review)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, Request
from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.moderation_flags import FlagRead, FlagScores, ModerationFlag
from src.db.organizations import Organization
from src.db.users import PublicUser, User

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 100


# ---------------------------------------------------------------------------
# RBAC: flags are NEVER visible to students or to the content's author.
# ---------------------------------------------------------------------------


async def is_moderation_staff(
    request: Request, user: object, org: Organization, db_session: AsyncSession
) -> bool:
    """Org admin/maintainer/superadmin, or a community moderator of this org."""
    if not isinstance(user, PublicUser) or not user.id:
        return False
    from src.security.org_auth import get_user_org_role, is_org_admin

    if await is_org_admin(user.id, org.id, db_session):  # type: ignore[arg-type]
        return True
    try:
        # Community moderator: the caller's role IN THIS ORG grants community
        # update. Deliberately not authorization_verify_based_on_roles: its
        # placeholder fallback can consider roles held in other orgs.
        role = await get_user_org_role(user.id, org.id, db_session)  # type: ignore[arg-type]
        rights: Any = (role.rights or {}) if role is not None else {}
        return bool((rights.get("communities") or {}).get("action_update"))
    except Exception as exc:  # noqa: BLE001 - deny on any RBAC failure
        logger.warning("moderation staff check failed (%s)", type(exc).__name__)
        return False


async def require_moderation_staff(
    request: Request, user: object, org_id: int, db_session: AsyncSession
) -> Organization:
    org = (await db_session.execute(select(Organization).where(Organization.id == org_id))).scalars().first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if not await is_moderation_staff(request, user, org, db_session):
        raise HTTPException(status_code=403, detail="Moderation staff only")
    from src.security.org_auth import enforce_org_mfa

    # Fail closed: an unexpected error here must deny access, not grant it.
    await enforce_org_mfa(user.id, org.id, db_session)  # type: ignore[attr-defined,arg-type]
    return org


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _strip_prefix(value: str, prefix: str) -> str:
    """The web routes re-add ``<prefix>_`` to their uuid segment, so emit it bare."""
    return value[len(prefix) :] if value.startswith(prefix) else value


async def _content_link(flag: ModerationFlag, db_session: AsyncSession) -> Optional[str]:
    """Org-relative app path to the flagged content, or None if it is gone.

    Shapes match the web routes, which prepend ``community_``/``discussion_``/
    ``assignment_`` themselves (so those prefixes are stripped here), and the
    user-analytics route, which takes the NUMERIC user id.
    """
    try:
        if flag.content_type == "discussion":
            from src.db.communities.communities import Community
            from src.db.communities.discussions import Discussion

            row = (
                await db_session.execute(
                    select(Community.community_uuid)
                    .join(Discussion, col(Discussion.community_id) == col(Community.id))
                    .where(Discussion.discussion_uuid == flag.content_uuid)
                )
            ).first()
            if not row:
                return None
            return (
                f"/community/{_strip_prefix(row[0], 'community_')}"
                f"/discussion/{_strip_prefix(flag.content_uuid, 'discussion_')}"
            )

        if flag.content_type == "discussion_comment":
            from src.db.communities.communities import Community
            from src.db.communities.discussion_comments import DiscussionComment
            from src.db.communities.discussions import Discussion

            row = (
                await db_session.execute(
                    select(Community.community_uuid, Discussion.discussion_uuid)
                    .join(Discussion, col(Discussion.community_id) == col(Community.id))
                    .join(DiscussionComment, col(DiscussionComment.discussion_id) == col(Discussion.id))
                    .where(DiscussionComment.comment_uuid == flag.content_uuid)
                )
            ).first()
            if not row:
                return None
            return (
                f"/community/{_strip_prefix(row[0], 'community_')}"
                f"/discussion/{_strip_prefix(row[1], 'discussion_')}"
            )

        if flag.content_type == "assignment_submission":
            from src.db.courses.assignments import Assignment, AssignmentUserSubmission

            row = (
                await db_session.execute(
                    select(Assignment.assignment_uuid)
                    .join(AssignmentUserSubmission, col(AssignmentUserSubmission.assignment_id) == col(Assignment.id))
                    .where(AssignmentUserSubmission.assignmentusersubmission_uuid == flag.content_uuid)
                )
            ).first()
            if not row:
                return None
            return f"/dash/assignments/{_strip_prefix(row[0], 'assignment_')}?subpage=submissions"

        if flag.content_type == "user_profile":
            # Route param is the numeric user id (content_uuid holds the user_uuid).
            user_id = (
                await db_session.execute(select(User.id).where(User.user_uuid == flag.content_uuid))
            ).scalars().first()
            return f"/dash/users/analytics/{user_id}" if user_id is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("content link resolution failed (%s)", type(exc).__name__)
    return None


async def _to_read(flags: list[ModerationFlag], db_session: AsyncSession) -> list[FlagRead]:
    user_ids = {f.author_user_id for f in flags} | {f.reviewed_by for f in flags if f.reviewed_by}
    uuids: dict[int, str] = {}
    if user_ids:
        rows = (await db_session.execute(select(User.id, User.user_uuid).where(col(User.id).in_(user_ids)))).all()
        uuids = {int(r[0]): r[1] for r in rows}

    out: list[FlagRead] = []
    for f in flags:
        raw = f.scores or {}
        out.append(
            FlagRead(
                flag_uuid=f.flag_uuid,
                org_id=f.org_id,
                content_type=f.content_type,
                content_uuid=f.content_uuid,
                author_user_uuid=uuids.get(f.author_user_id),
                kind=f.kind,
                severity=f.severity,
                scores=FlagScores(
                    pii=float(raw.get("pii") or 0.0),
                    toxicity=float(raw.get("toxicity") or 0.0),
                    spam=float(raw.get("spam") or 0.0),
                    academic_integrity=(
                        float(raw["academic_integrity"]) if raw.get("academic_integrity") is not None else None
                    ),
                ),
                reasons=[str(r) for r in (f.reasons or [])],
                status=f.status,
                reviewed_by_user_uuid=uuids.get(f.reviewed_by) if f.reviewed_by else None,
                reviewed_at=f.reviewed_at,
                created_at=f.created_at,
                content_link=await _content_link(f, db_session),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _requester_id(user: object) -> Optional[int]:
    uid = getattr(user, "id", None)
    return int(uid) if uid else None


def _not_own(user: object) -> list[Any]:
    """Authors never see flags about their own content, even when staff."""
    uid = _requester_id(user)
    return [ModerationFlag.author_user_id != uid] if uid is not None else []


async def _grader_course_uuids(
    request: Request,
    user: object,
    org: Organization,
    submission_uuids: list[str],
    db_session: AsyncSession,
) -> dict[str, bool]:
    """Map submission uuid -> whether *user* may grade it (course-scoped, same org)."""
    if not submission_uuids or not isinstance(user, PublicUser) or not user.id:
        return {}
    from src.db.courses.assignments import Assignment, AssignmentUserSubmission
    from src.db.courses.courses import Course
    from src.services.courses.activities.assignments import _is_assignment_instructor

    rows = (
        await db_session.execute(
            select(AssignmentUserSubmission.assignmentusersubmission_uuid, Course.course_uuid)
            .join(Assignment, col(AssignmentUserSubmission.assignment_id) == col(Assignment.id))
            .join(Course, col(Assignment.course_id) == col(Course.id))
            .where(
                col(AssignmentUserSubmission.assignmentusersubmission_uuid).in_(submission_uuids),
                Assignment.org_id == org.id,
                Course.org_id == org.id,
            )
        )
    ).all()
    per_course: dict[str, bool] = {}
    out: dict[str, bool] = {}
    for sub_uuid, course_uuid in rows:
        if course_uuid not in per_course:
            try:
                per_course[course_uuid] = bool(
                    await _is_assignment_instructor(request, user, course_uuid, db_session)
                )
            except Exception as exc:  # noqa: BLE001 - deny on any RBAC failure
                logger.warning("assignment staff check failed (%s)", type(exc).__name__)
                per_course[course_uuid] = False
        out[sub_uuid] = per_course[course_uuid]
    return out


async def require_flag_reader(
    request: Request,
    user: object,
    org_id: int,
    db_session: AsyncSession,
    *,
    assignment_scope: bool,
) -> tuple[Organization, bool]:
    """Org moderation staff, or (when *assignment_scope*) any org member who may
    later be narrowed to assignment submissions they teach.

    Returns ``(org, is_staff)``. Non-staff callers MUST be narrowed by the
    service functions below; the org-wide queue never passes ``assignment_scope``.
    """
    org = (await db_session.execute(select(Organization).where(Organization.id == org_id))).scalars().first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if await is_moderation_staff(request, user, org, db_session):
        is_staff = True
    elif assignment_scope and isinstance(user, PublicUser) and user.id:
        from src.security.org_auth import get_user_org

        if await get_user_org(user.id, org.id, db_session) is None:  # type: ignore[arg-type]
            raise HTTPException(status_code=403, detail="Moderation staff only")
        is_staff = False
    else:
        raise HTTPException(status_code=403, detail="Moderation staff only")
    from src.security.org_auth import enforce_org_mfa

    # Fail closed: an unexpected error here must deny access, not grant it.
    await enforce_org_mfa(user.id, org.id, db_session)  # type: ignore[attr-defined,arg-type]
    return org, is_staff


async def list_flags(
    org_id: int,
    db_session: AsyncSession,
    *,
    status: str = "open",
    content_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    requester: object = None,
) -> tuple[list[FlagRead], int]:
    limit = max(1, min(int(limit), MAX_PAGE_SIZE))
    offset = max(0, int(offset))
    cond = [ModerationFlag.org_id == org_id, *_not_own(requester)]
    if status and status != "all":
        cond.append(ModerationFlag.status == status)
    if content_type:
        cond.append(ModerationFlag.content_type == content_type)

    total = (await db_session.execute(select(func.count()).select_from(ModerationFlag).where(*cond))).scalar_one()
    rows = (
        await db_session.execute(
            select(ModerationFlag)
            .where(*cond)
            .order_by(col(ModerationFlag.created_at).desc(), col(ModerationFlag.id).desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return await _to_read(list(rows), db_session), int(total)


async def flags_by_content(
    org_id: int,
    content_type: Optional[str],
    content_uuid: str,
    db_session: AsyncSession,
    *,
    requester: object = None,
    request: Optional[Request] = None,
    is_staff: bool = True,
) -> list[FlagRead]:
    if not is_staff:
        # Instructor path: only assignment submissions in a course they teach.
        if content_type != "assignment_submission" or request is None:
            raise HTTPException(status_code=403, detail="Moderation staff only")
        org = (await db_session.execute(select(Organization).where(Organization.id == org_id))).scalars().first()
        allowed = await _grader_course_uuids(request, requester, org, [content_uuid], db_session) if org else {}
        if not allowed.get(content_uuid):
            raise HTTPException(status_code=403, detail="Moderation staff only")
    cond = [ModerationFlag.org_id == org_id, ModerationFlag.content_uuid == content_uuid, *_not_own(requester)]
    if content_type:
        cond.append(ModerationFlag.content_type == content_type)
    rows = (
        await db_session.execute(
            select(ModerationFlag).where(*cond).order_by(col(ModerationFlag.created_at).desc())
        )
    ).scalars().all()
    return await _to_read(list(rows), db_session)


async def _has_instructor_rights(user: object, org_id: int, db_session: AsyncSession) -> bool:
    """Caller's role IN THIS ORG grants course update (instructor-level) rights.

    Cheap pre-filter only; per-course grading authority is still enforced per row.
    """
    if not isinstance(user, PublicUser) or not user.id:
        return False
    try:
        from src.security.org_auth import get_user_org_role

        role = await get_user_org_role(user.id, org_id, db_session)  # type: ignore[arg-type]
        rights: Any = (role.rights or {}) if role is not None else {}
        courses: Any = rights.get("courses") or {}
        return bool(courses.get("action_update") or courses.get("action_update_own"))
    except Exception as exc:  # noqa: BLE001 - deny on any RBAC failure
        logger.warning("instructor rights check failed (%s)", type(exc).__name__)
        return False


async def flags_by_user(
    org_id: int,
    user_uuid: str,
    db_session: AsyncSession,
    *,
    requester: object = None,
    request: Optional[Request] = None,
    is_staff: bool = True,
) -> list[FlagRead]:
    if not is_staff and not await _has_instructor_rights(requester, org_id, db_session):
        # Answer before touching users/flags so timing cannot reveal whether the
        # target has assignment flags (students and non-instructors get nothing).
        return []
    user_id = (await db_session.execute(select(User.id).where(User.user_uuid == user_uuid))).scalars().first()
    if user_id is None:
        return []
    cond = [ModerationFlag.org_id == org_id, ModerationFlag.author_user_id == user_id, *_not_own(requester)]
    if not is_staff:
        cond.append(ModerationFlag.content_type == "assignment_submission")
    rows = list(
        (
            await db_session.execute(
                select(ModerationFlag).where(*cond).order_by(col(ModerationFlag.created_at).desc())
            )
        ).scalars().all()
    )
    if not is_staff:
        org = (await db_session.execute(select(Organization).where(Organization.id == org_id))).scalars().first()
        allowed = (
            await _grader_course_uuids(request, requester, org, [f.content_uuid for f in rows], db_session)
            if org is not None and request is not None
            else {}
        )
        rows = [f for f in rows if allowed.get(f.content_uuid)]
    return await _to_read(rows, db_session)


async def update_flag_status(
    request: Request,
    flag_uuid: str,
    new_status: str,
    user: object,
    db_session: AsyncSession,
) -> FlagRead:
    flag = (
        await db_session.execute(select(ModerationFlag).where(ModerationFlag.flag_uuid == flag_uuid))
    ).scalars().first()
    org = None
    if flag is not None:
        org = (await db_session.execute(select(Organization).where(Organization.id == flag.org_id))).scalars().first()
    # Same answer for "missing" and "not allowed": no flag-id probing.
    if flag is None or org is None or not await is_moderation_staff(request, user, org, db_session):
        raise HTTPException(status_code=404, detail="Flag not found")
    if flag.author_user_id == _requester_id(user):
        # Authors never see (or act on) flags about their own content.
        raise HTTPException(status_code=404, detail="Flag not found")
    from src.security.org_auth import enforce_org_mfa

    await enforce_org_mfa(user.id, org.id, db_session)  # type: ignore[attr-defined,arg-type]

    flag.status = new_status
    if new_status == "open":
        flag.reviewed_by = None
        flag.reviewed_at = None
    else:
        flag.reviewed_by = user.id  # type: ignore[attr-defined]
        flag.reviewed_at = datetime.now(timezone.utc).isoformat()
    db_session.add(flag)
    await db_session.commit()
    await db_session.refresh(flag)
    return (await _to_read([flag], db_session))[0]
