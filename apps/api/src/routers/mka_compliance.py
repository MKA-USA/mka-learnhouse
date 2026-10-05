"""MKA fork: native compliance analytics endpoints (mounted at /mka/compliance). Spec 2026-10-04 sections 2 + 4.

Authentication: the router-level dependency admits a session OR an org API token; every handler decides.

* Import (``POST /cycles``, ``POST /expected/import``, ``DELETE /cycles/{id}/expected``): org ADMIN session
  (``org_id`` / ``org_slug``) OR org API token (``org_slug``): the same ``_resolve_admin`` as /mka/attributes.
* Reads (``/scope``, ``/overview``, ``/courses/{uuid}/...``): ``compliance_scope.resolve_scope`` decides
  ``all`` / ``own`` / ``none``. API tokens are ``all`` for their own org only.

The org is NEVER taken on trust: sessions must be members of the ``org_id`` they pass, tokens must match the
token's org. Every response is ``Cache-Control: private, no-store``.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.routers.mka_attributes import _resolve_admin
from src.security.auth import get_authenticated_user
from src.db.users import APITokenUser, SuperadminAPITokenUser
from src.services.mka import automation_reminders as reminders
from src.services.mka import compliance as svc
from src.services.mka import compliance_import as imp
from src.services.mka import compliance_scope as scope_svc

router = APIRouter()


class CyclesIn(BaseModel):
    """The provisioner's ``out/cycle-courses.json`` (extra keys such as ``generatedAt`` / ``activities`` ignored)."""

    model_config = ConfigDict(extra="ignore")

    cycle: Optional[str] = Field(default=None, max_length=100)
    label: Optional[str] = Field(default=None, max_length=100)
    deadline: Optional[str] = None
    deadline_on: Optional[str] = None
    starts_on: Optional[str] = None
    courses: list[Any] = Field(max_length=imp.MAX_COURSE_ROWS)  # raw: a malformed entry is a per-row error


class ExpectedImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: Optional[int] = None
    cycle: Optional[str] = Field(default=None, max_length=100, description="cycle label (alternative to cycle_id)")
    # Rows stay raw dicts: a malformed row is reported per row, it must not 422 the whole batch.
    rows: list[Any] = Field(max_length=imp.MAX_EXPECTED_ROWS)
    dry_run: bool = False


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _filename(course_uuid: str) -> str:
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in course_uuid)[:80]
    return f"chase-list-{safe}.csv"


async def _admin(current_user, org_id, org_slug, db):
    """Org admin session or org token that may update the org (H1)."""
    # token_right=TOKEN_WRITE_FULL: the shared resolver checks the Full Access update rights (not the read default)
    return await _resolve_admin(current_user, org_id, org_slug, db, allow_token=True, token_right=scope_svc.TOKEN_WRITE_FULL)


async def _viewer_context(
    request: Request, response: Response, current_user, org_id, org_slug, cycle_id, db: AsyncSession
):
    _private(response)
    scope = await scope_svc.resolve_scope(request, current_user, org_id, org_slug, db)
    if scope.kind == "none":  # spec: everyone else gets nothing (no cycle labels / deadlines either)
        return scope, None
    cycle = await scope_svc.get_cycle(db, scope.org_id, cycle_id, svc.today())
    return scope, cycle


# ---------------------------------------------------------------------------------------------------------
# import (org admin session OR org API token)
# ---------------------------------------------------------------------------------------------------------

@router.post("/cycles")
async def api_upsert_cycle(
    body: CyclesIn,
    response: Response,
    org_id: Optional[int] = Query(None, description="Session admins: the org"),
    org_slug: Optional[str] = Query(None, description="API tokens: the token's org slug"),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Upsert a cycle (by label) and its courses; idempotent; per-course errors, one bad course never aborts."""
    _private(response)
    admin = await _admin(current_user, org_id, org_slug, db_session)
    return await imp.upsert_cycle(db_session, admin.org_id, body.model_dump(exclude_none=False))


@router.post("/expected/import")
async def api_import_expected(
    body: ExpectedImportIn,
    response: Response,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Upsert expected-roster rows (<= 2000 per request), keyed by (cycle, email, department, level, role_title).
    One bad row never aborts the batch; each failure is returned with its row index."""
    _private(response)
    admin = await _admin(current_user, org_id, org_slug, db_session)
    cycle = await imp.require_cycle(db_session, admin.org_id, cycle_id=body.cycle_id, label=body.cycle)
    return await imp.import_expected(db_session, admin.org_id, cycle, body.rows, dry_run=body.dry_run)


@router.delete("/cycles/{cycle_id}/expected")
async def api_clear_expected(
    cycle_id: int,
    response: Response,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Clear the expected roster of one cycle (for a re-import)."""
    _private(response)
    admin = await _admin(current_user, org_id, org_slug, db_session)
    cycle = await imp.require_cycle(db_session, admin.org_id, cycle_id=cycle_id, label=None)
    return {"cycle_id": cycle.id, "deleted": await imp.clear_expected(db_session, admin.org_id, cycle)}


# ---------------------------------------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------------------------------------

@router.get("/scope")
async def api_scope(
    request: Request,
    response: Response,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    cycle_id: Optional[int] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """What the viewer may see (drives nav / tab visibility). Never 403 for a plain org member: ``scope: none``."""
    scope, cycle = await _viewer_context(request, response, current_user, org_id, org_slug, cycle_id, db_session)
    rows = []
    if cycle is not None:
        rows = scope_svc.visible_courses(scope, await scope_svc.cycle_courses(db_session, scope.org_id, cycle.id))
    return {
        "scope": scope.kind,
        "cycle": svc.cycle_view(cycle),
        "cycles": [] if scope.kind == "none" else [
            svc.cycle_view(c) for c in await scope_svc.all_cycles(db_session, scope.org_id)
        ],
        "courses": [svc.course_view(cc, course) for cc, course in rows],
        "departments": sorted({cc.department for cc, _ in rows if cc.department}),
    }


@router.get("/overview")
async def api_overview(
    request: Request,
    response: Response,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    cycle_id: Optional[int] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    scope, cycle = await _viewer_context(request, response, current_user, org_id, org_slug, cycle_id, db_session)
    scope_svc.require_all(scope)
    if cycle is None:
        return svc.build_overview(None, None, svc.today())
    rows = await scope_svc.cycle_courses(db_session, scope.org_id, cycle.id)
    ds = await svc.load_dataset(
        db_session, scope.org_id, cycle, [cc for cc, _ in rows], {c.id: c for _, c in rows}
    )
    return svc.build_overview(ds, cycle, svc.today())


async def _course_dataset(request, response, current_user, org_id, org_slug, cycle_id, course_uuid, db_session):
    scope, cycle = await _viewer_context(request, response, current_user, org_id, org_slug, cycle_id, db_session)
    link, course = await scope_svc.resolve_course(db_session, scope, cycle, course_uuid)  # 403 none / 404 not yours
    ds = await svc.load_dataset(db_session, scope.org_id, cycle, [link], {course.id: course})
    return ds, link, course


def _filters(status, stage, overdue, region, majlis, level, department, q) -> dict:
    return {
        "status": status, "stage": stage, "overdue": overdue, "region": region, "majlis": majlis,
        "level": level, "department": department, "q": q,
    }


@router.get("/courses/{course_uuid}/summary")
async def api_course_summary(
    course_uuid: str,
    request: Request,
    response: Response,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    cycle_id: Optional[int] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    ds, link, course = await _course_dataset(
        request, response, current_user, org_id, org_slug, cycle_id, course_uuid, db_session
    )
    return svc.build_summary(ds, link, course, svc.today())


@router.get("/courses/{course_uuid}/learners")
async def api_course_learners(
    course_uuid: str,
    request: Request,
    response: Response,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    cycle_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, max_length=200, description="comma list of: not_signed_in,not_started,in_progress,completed,attested,overdue"),
    stage: Optional[str] = Query(None, max_length=200),
    overdue: Optional[bool] = Query(None),
    region: Optional[str] = Query(None, max_length=200),
    majlis: Optional[str] = Query(None, max_length=200),
    level: Optional[str] = Query(None, max_length=100),
    department: Optional[str] = Query(None, max_length=200),
    q: Optional[str] = Query(None, max_length=100),
    sort: Optional[str] = Query(None, max_length=30, description="[-]name|status|last_activity|progress (default status: most urgent first)"),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(svc.DEFAULT_PAGE_SIZE, ge=1, le=svc.MAX_PAGE_SIZE),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    ds, link, course = await _course_dataset(
        request, response, current_user, org_id, org_slug, cycle_id, course_uuid, db_session
    )
    return svc.build_learners(
        ds, link, course, svc.today(), filters=_filters(status, stage, overdue, region, majlis, level, department, q),
        sort=sort, page=page, page_size=page_size,
    )


@router.get("/courses/{course_uuid}/learners.csv")
async def api_course_learners_csv(
    course_uuid: str,
    request: Request,
    response: Response,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    cycle_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, max_length=200),
    stage: Optional[str] = Query(None, max_length=200),
    overdue: Optional[bool] = Query(None),
    region: Optional[str] = Query(None, max_length=200),
    majlis: Optional[str] = Query(None, max_length=200),
    level: Optional[str] = Query(None, max_length=100),
    department: Optional[str] = Query(None, max_length=200),
    q: Optional[str] = Query(None, max_length=100),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> Response:
    """The chase list: who is not yet attested (after the filters), most overdue first. Same scope as the JSON."""
    ds, link, _course = await _course_dataset(
        request, response, current_user, org_id, org_slug, cycle_id, course_uuid, db_session
    )
    text, truncated = svc.build_chase_csv(
        ds, link, svc.today(), filters=_filters(status, stage, overdue, region, majlis, level, department, q)
    )
    headers = {
        "Cache-Control": "private, no-store",
        "Content-Disposition": f'attachment; filename="{_filename(link.course_uuid)}"',
        "X-Content-Type-Options": "nosniff",
    }
    if truncated:
        headers["X-Truncated"] = "true"  # header only: a marker row would corrupt the chase list
        headers["X-Row-Limit"] = str(svc.MAX_CSV_ROWS)
    return Response(content=text, media_type="text/csv; charset=utf-8", headers=headers)


@router.get("/courses/{course_uuid}/trend")
async def api_course_trend(
    course_uuid: str,
    request: Request,
    response: Response,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    cycle_id: Optional[int] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Cumulative completed / attested per day (derived from step and sign-off timestamps) vs the expected curve."""
    ds, link, course = await _course_dataset(
        request, response, current_user, org_id, org_slug, cycle_id, course_uuid, db_session
    )
    return svc.build_trend(ds, link, course, svc.today())


# ---------------------------------------------------------------------------------------------------------
# manual "Remind" button (seam C)
# ---------------------------------------------------------------------------------------------------------

@router.post("/courses/{course_uuid}/remind")
async def api_remind_course(
    course_uuid: str,
    request: Request,
    response: Response,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    cycle_id: Optional[int] = Query(None),
    dry_run: bool = Query(True, description="Preview the counts only (default); false sends"),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Remind the people still outstanding on this course. Session users only (API tokens: 403); the course must be
    in the viewer's compliance scope (404 otherwise); only the CURRENT, started cycle can be reminded (409; the
    ``cycle_id`` is never trusted for sending); at most one real remind per course per 24 h (429)."""
    _private(response)
    if isinstance(current_user, (APITokenUser, SuperadminAPITokenUser)):
        raise HTTPException(status_code=403, detail="A user session is required")
    scope, cycle = await _viewer_context(request, response, current_user, org_id, org_slug, cycle_id, db_session)
    link, course = await scope_svc.resolve_course(db_session, scope, cycle, course_uuid)  # 403 none / 404 not yours
    org = await db_session.get(reminders.Organization, scope.org_id)
    try:
        return await reminders.remind_course(
            db_session, org=org, cycle=cycle, link=link, course=course, viewer_id=current_user.id, dry_run=dry_run,
        )
    except reminders.ManualRemindBlocked as blocked:
        headers = {"Retry-After": str(blocked.retry_after)} if blocked.retry_after else None
        raise HTTPException(status_code=blocked.status_code, detail=blocked.detail, headers=headers)
