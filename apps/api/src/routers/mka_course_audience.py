"""MKA fork: course audience endpoints (mounted at /mka/courses). Spec 2026-10-08-mka-course-audience-design.md section 3.A.

* ``GET    /{course_uuid}/audience``          ``{audience, mode, rule, usergroup_id, matched_count}`` or ``{audience: null}``
* ``POST   /{course_uuid}/audience/preview``  body ``{audience, mode, rule}`` -> ``{matched_count, sample, would_enroll}`` (no writes)
* ``PUT    /{course_uuid}/audience``          body as above -> ``{memberships_added, memberships_removed, enrolled, matched_count}``
* ``DELETE /{course_uuid}/audience``          removes the row + managed group; enrolments stay
* ``GET    /audience/options?org_id=``        departments, levels, roles (any org member)

Authz: a session user must be a superadmin, an org admin/maintainer or an active author of THE course
(``audience.course_author_or_admin``); an org API token must belong to the course's org and carry ``courses.action_update``
(``courses.action_read`` for the GET). ``MKA_COURSE_AUDIENCE_ENABLED`` off: GET and preview still work, writes are 404.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.courses.courses import Course
from src.db.users import APITokenUser, SuperadminAPITokenUser
from src.security.auth import get_authenticated_user
from src.services.mka import attributes as attrs_svc
from src.services.mka import audience as audience_svc
from src.services.mka import course_audience as svc
from src.services.mka.audience_config import build_options
from src.services.mka.token_rights import token_may

router = APIRouter()
NO_STORE = "private, no-store"
MAX_DB_INT = 2_147_483_647


class CustomRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    departments: list[str] = Field(default_factory=list, max_length=svc.MAX_VALUES)
    levels: list[str] = Field(default_factory=list, max_length=svc.MAX_VALUES)
    roles: list[str] = Field(default_factory=list, max_length=svc.MAX_VALUES)


class AudienceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audience: Literal["everyone", "officeholders", "custom"]
    mode: Literal["required", "optin"]
    rule: CustomRuleIn | None = None


async def _course(db: AsyncSession, course_uuid: str) -> Course:
    course = (await db.execute(select(Course).where(Course.course_uuid == course_uuid))).scalars().first()
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


async def _authorize(request: Request, current_user, course: Course, db: AsyncSession, *, write: bool) -> int | None:
    """The acting user id (None for an org API token). Org boundary enforced for tokens; 403 for everyone else."""
    if isinstance(current_user, SuperadminAPITokenUser):
        raise HTTPException(status_code=403, detail="Use an organization API token")
    if isinstance(current_user, APITokenUser):
        if current_user.org_id != course.org_id:
            raise HTTPException(status_code=403, detail="API token does not belong to this course's organization")
        token_may(current_user, ("courses", "action_update" if write else "action_read"))
        return None
    return await audience_svc.course_author_or_admin(request, current_user, course.org_id, course.course_uuid, db)


def _need_enabled() -> None:
    if not svc.enabled():
        raise HTTPException(status_code=404, detail="Course audiences are not enabled")


def _spec(body: AudienceIn) -> tuple[str, str, dict | None]:
    try:
        custom = svc.normalize_custom(body.audience, body.rule.model_dump() if body.rule else None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return body.audience, body.mode, custom


@router.get("/audience/options")
async def api_options(
    response: Response,
    org_id: int = Query(..., ge=1, le=MAX_DB_INT),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    await audience_svc.require_org_member(current_user, org_id, db_session)
    response.headers["Cache-Control"] = NO_STORE
    opts = build_options(attrs_svc.get_rules())
    return {
        "departments": [{"key": d["key"], "name": d["name"]} for d in opts["departments"]],
        "levels": opts["levels"],
        "roles": [{"key": r["key"], "title": r["title"], "plural": r["plural"]} for r in opts["roles"]],
    }


@router.get("/{course_uuid}/audience")
async def api_get(
    request: Request, response: Response,
    course_uuid: str = Path(..., max_length=200),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    course = await _course(db_session, course_uuid)
    await _authorize(request, current_user, course, db_session, write=False)
    response.headers["Cache-Control"] = NO_STORE
    return await svc.get(db_session, course)


@router.post("/{course_uuid}/audience/preview")
async def api_preview(
    body: AudienceIn, request: Request, response: Response,
    course_uuid: str = Path(..., max_length=200),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    course = await _course(db_session, course_uuid)
    await _authorize(request, current_user, course, db_session, write=True)
    audience, mode, custom = _spec(body)
    response.headers["Cache-Control"] = NO_STORE
    return await svc.preview(db_session, course, audience, mode, custom)


@router.put("/{course_uuid}/audience")
async def api_put(
    body: AudienceIn, request: Request, response: Response,
    course_uuid: str = Path(..., max_length=200),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    course = await _course(db_session, course_uuid)
    actor = await _authorize(request, current_user, course, db_session, write=True)
    _need_enabled()
    audience, mode, custom = _spec(body)
    response.headers["Cache-Control"] = NO_STORE
    try:
        return await svc.apply(db_session, course, audience, mode, custom, actor)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        await db_session.rollback()
        raise HTTPException(status_code=500, detail="applying the audience failed; see the server log")


@router.delete("/{course_uuid}/audience")
async def api_delete(
    request: Request, response: Response,
    course_uuid: str = Path(..., max_length=200),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    course = await _course(db_session, course_uuid)
    await _authorize(request, current_user, course, db_session, write=True)
    _need_enabled()
    response.headers["Cache-Control"] = NO_STORE
    return await svc.remove(db_session, course)
