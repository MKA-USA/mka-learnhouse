"""MKA fork: identity-attribute endpoints (mounted at /mka/attributes). Spec A7.

Authentication (router-level dependency admits a session OR an org API token;
every handler then decides):

* ``GET /me``                      session only (the viewer's OWN values).
* admin routes (list/get/audit/    org ADMIN session (``org_id``) OR an org API
  recompute/roster/review queue)   token (``Authorization: Bearer lh_...`` with
                                   ``org_slug``): the SAME pattern as upstream's
                                   ``/admin/{org_slug}/...`` routes, i.e.
                                   ``_require_api_token`` + ``_resolve_org_slug``
                                   (token's org must match the slug; plan gate).
* override set/clear               org ADMIN session only (needs a human actor
                                   for the audit trail).

Attributes are never writable by the user and never returned to other users.

Audience block routes (contract docs/superpowers/specs/2026-10-05-mka-audience-contracts.md s2), all session-only
(API tokens get 403) and ``Cache-Control: private, no-store``:

* ``GET  /me?course_uuid=``          the viewer; ``can_view_all`` is also true for an author of THAT course.
* ``GET  /options?org_id=``          picker vocabulary (any org member).
* ``POST /audience/count``           aggregate audience size (superadmin / org admin / author of the course).
* ``GET  /me/counterparts``          who to contact (viewer's own role mailboxes).
* ``GET/POST /preview-people[...]``  org admin / maintainer / superadmin: find a person, read their effective attributes.
"""

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.mka_user_attributes import MkaRosterOverride
from src.db.organizations import Organization
from src.db.user_organizations import UserOrganization
from src.db.users import APITokenUser, SuperadminAPITokenUser, User
from src.routers.mka_profile import _uid
from src.security.auth import get_authenticated_user
from src.security.org_auth import enforce_org_mfa, get_user_org
from src.security.rbac.constants import ADMIN_OR_MAINTAINER_ROLE_IDS, is_admin
from src.security.superadmin import is_user_superadmin
from src.services.admin.admin import _require_api_token, _resolve_org_slug
from src.services.mka import attributes as svc
from src.services.mka import audience as audience_svc
from src.services.mka.audience_config import build_options
from src.services.mka.counterparts import counterparts_for
from src.services.mka.token_rights import TOKEN_READ, TOKEN_WRITE_FULL, token_may

router = APIRouter()

REVIEW_STATUSES = ["unrecognized", "ambiguous", "partial"]
MAX_ROSTER_IMPORT = 1000
MAX_DB_INT = 2_147_483_647  # ids are int4: a bigger number is a 422, never a database error
NO_STORE = "private, no-store"
MAX_COUNT_BODY = 128 * 1024  # a valid body is org_id + <= 64 KB rule; anything bigger is refused before parsing


# ---------------------------------------------------------------------------
# request bodies
# ---------------------------------------------------------------------------

class OverrideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    override: dict
    reason: str = Field(min_length=1, max_length=1000)


class RosterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attributes: dict
    note: Optional[str] = Field(default=None, max_length=1000)


class RosterRowIn(RosterIn):
    email: str = Field(max_length=320)


class RosterImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[RosterRowIn] = Field(max_length=MAX_ROSTER_IMPORT)
    dry_run: bool = False


class RecomputeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False


class AudienceCountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_id: StrictInt = Field(ge=1, le=MAX_DB_INT)
    course_uuid: Optional[str] = Field(default=None, max_length=200)
    rule: Any  # raw on purpose: audience_eval.validate_rule is the one validator (invalid => 422 with its message)


# ---------------------------------------------------------------------------
# authz helpers
# ---------------------------------------------------------------------------

class _Admin:
    """Resolved admin context for an admin route."""

    def __init__(self, org_id: int, actor_user_id: Optional[int], source: str):
        self.org_id = org_id
        self.actor_user_id = actor_user_id  # None for API tokens (system actor)
        self.source = source  # 'admin' (session) | 'companion' (API token)


async def _resolve_admin(
    current_user, org_id: Optional[int], org_slug: Optional[str], db_session: AsyncSession,
    allow_token: bool = False,
    token_right: tuple = TOKEN_READ,
) -> _Admin:
    # API token: upstream /admin/{org_slug}/... authentication plus a token-rights check. Tokens are limited to the routes the companion service
    # needs (list + roster); every other admin route passes allow_token=False.
    if isinstance(current_user, APITokenUser):
        if not allow_token:
            raise HTTPException(status_code=403, detail="Not available to API tokens")
        if not org_slug:
            raise HTTPException(status_code=422, detail="org_slug is required for API-token access")
        token_user = _require_api_token(current_user)
        token_may(token_user, *token_right)     # empty rights refused; reads need courses+assignments read, writes all Full Access update rights
        org = await _resolve_org_slug(org_slug, token_user, db_session)
        return _Admin(org.id, None, "companion")
    if isinstance(current_user, SuperadminAPITokenUser):
        raise HTTPException(status_code=403, detail="Use an organization API token")

    caller = _uid(current_user)  # 403 without a user session
    if org_id is None and org_slug:
        org = (
            await db_session.execute(select(Organization).where(Organization.slug == org_slug))
        ).scalars().first()
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        org_id = org.id
    if org_id is None:
        raise HTTPException(status_code=422, detail="org_id (or org_slug) is required")
    if not await is_user_superadmin(caller, db_session):
        caller_org = await get_user_org(caller, org_id, db_session)
        if caller_org is None or not is_admin(caller_org.role_id):
            raise HTTPException(status_code=403, detail="Admin access required")
        await enforce_org_mfa(caller, org_id, db_session)
    return _Admin(org_id, caller, "admin")


async def _target_user(admin: _Admin, user_id: int, db_session: AsyncSession) -> User:
    """The target must exist and be a member of the admin's org."""
    member = (
        await db_session.execute(
            select(UserOrganization).where(
                UserOrganization.user_id == user_id, UserOrganization.org_id == admin.org_id
            )
        )
    ).scalars().first()
    user = await db_session.get(User, user_id) if member is not None else None
    if user is None:
        raise HTTPException(status_code=404, detail="User not found in this organization")
    return user


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# viewer
# ---------------------------------------------------------------------------

@router.get("/me")
async def api_get_me(
    request: Request,
    response: Response,
    course_uuid: Optional[str] = Query(None, max_length=200, description="Audience block: also grant can_view_all to an author of THIS course"),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """The signed-in user's own effective attributes (no source / flag metadata).

    A user with no stored row yet is reported as ``unrecognized`` (unknown), never as "not an officeholder".
    ``can_view_all``: without a ``course_uuid`` (or with an unknown one: no 404, no information) it is true for org
    admins/maintainers of ANY org and superadmins. When ``course_uuid`` names an existing course it is true only for a superadmin,
    an admin/maintainer of THAT course's org, or an ACTIVE author of the course (CREATOR/MAINTAINER/CONTRIBUTOR passing the
    upstream ``update`` check and a member of the org).
    """
    uid = _uid(current_user)
    response.headers["Cache-Control"] = NO_STORE
    me = await db_session.get(User, uid)
    attrs, stale = svc.read_effective_from_row(await svc.get_row(db_session, uid), me)  # fails closed
    # With a course that exists, the course decides (an admin of ANOTHER org gets false); otherwise the legacy any-org rule.
    can_view_all = await audience_svc.course_view_all(request, uid, course_uuid, db_session)
    if can_view_all is None:
        can_view_all = await is_user_superadmin(uid, db_session)
        if not can_view_all:
            can_view_all = (
                await db_session.execute(
                    select(UserOrganization.org_id).where(
                        UserOrganization.user_id == uid,
                        UserOrganization.role_id.in_(ADMIN_OR_MAINTAINER_ROLE_IDS),  # type: ignore[attr-defined]
                    )
                )
            ).first() is not None
    return {
        "attributes": attrs,
        "stale": stale,
        "can_view_all": can_view_all,
        "rules_version": svc.get_rules().version,
    }


# ---------------------------------------------------------------------------
# audience block (contract s2): options, count, counterparts, preview-as
# ---------------------------------------------------------------------------

@router.get("/options")
async def api_audience_options(
    response: Response,
    org_id: int = Query(..., ge=1, le=MAX_DB_INT),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Picker vocabulary: levels, departments, roles, regions, Majlis, presets, personas, copy. Any member of the org."""
    await audience_svc.require_org_member(current_user, org_id, db_session)
    response.headers["Cache-Control"] = NO_STORE
    return build_options(svc.get_rules())


def _reject_constant(name: str):
    raise ValueError(f"{name} is not allowed in JSON")


async def _count_body(request: Request) -> AudienceCountIn:
    """Parse the count body ourselves: NaN / Infinity anywhere, bad JSON, oversize or a wrong shape are a plain 422 (FastAPI would echo
    a NaN in its error body and fail to serialise it)."""
    raw = await request.body()
    if len(raw) > MAX_COUNT_BODY:
        raise HTTPException(status_code=422, detail="request body is too large")
    try:
        data = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, RecursionError):  # JSONDecodeError and UnicodeDecodeError are ValueErrors
        raise HTTPException(status_code=422, detail="request body must be valid JSON")
    try:
        return AudienceCountIn.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False, include_context=False, include_input=False))


@router.post("/audience/count")
async def api_audience_count(
    request: Request,
    response: Response,
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """How many members of the org the rule currently reaches. Aggregates only (never names). Authors count only for THEIR course.
    Body: ``{org_id: int, course_uuid?: str, rule: <rule, at most 64 KB serialized>}``."""
    body = await _count_body(request)
    await audience_svc.course_author_or_admin(request, current_user, body.org_id, body.course_uuid, db_session)
    rule = audience_svc.parse_rule_or_422(body.rule)
    response.headers["Cache-Control"] = NO_STORE
    return await audience_svc.count_audience(db_session, body.org_id, rule)


@router.get("/me/counterparts")
async def api_get_counterparts(
    response: Response,
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """The viewer's department-head / regional-Qaid / Majlis-nazim mailboxes, from the identity rules (never someone else's data)."""
    uid = _uid(current_user)
    response.headers["Cache-Control"] = NO_STORE
    me = await db_session.get(User, uid)
    attrs, _stale = svc.read_effective_from_row(await svc.get_row(db_session, uid), me)  # fails closed
    return counterparts_for(attrs, svc.get_rules(), own_email=me.email)  # type: ignore[union-attr]


@router.get("/preview-people")
async def api_preview_people(
    response: Response,
    org_id: int = Query(..., ge=1, le=MAX_DB_INT),
    q: str = Query(..., min_length=2, max_length=100),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Find an org member to preview as. Org admin / maintainer / superadmin only. At most 20; no attributes in the list."""
    await audience_svc.require_org_admin(current_user, org_id, db_session)
    if len(q.strip()) < 2:
        raise HTTPException(status_code=422, detail="q must have at least 2 characters")
    response.headers["Cache-Control"] = NO_STORE
    return {"people": await audience_svc.search_people(db_session, org_id, q)}


@router.post("/preview-people/{user_id}")
async def api_preview_person(
    response: Response,
    user_id: int = Path(..., ge=1, le=MAX_DB_INT),
    org_id: int = Query(..., ge=1, le=MAX_DB_INT),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """The person's EFFECTIVE attributes (fail-closed reader), audited as ``preview_as`` with the admin as actor."""
    actor = await audience_svc.require_org_admin(current_user, org_id, db_session)
    response.headers["Cache-Control"] = NO_STORE
    return await audience_svc.preview_person(db_session, org_id, actor, user_id)


# ---------------------------------------------------------------------------
# admin: list / review queue / user detail / audit
# ---------------------------------------------------------------------------

def _csv(value: Optional[str]) -> Optional[list[str]]:
    if not value:
        return None
    items = [v.strip() for v in value.split(",") if v.strip()]
    return items or None


@router.get("/users")
async def api_list_users(
    org_id: Optional[int] = Query(None, description="Session admins: the org"),
    org_slug: Optional[str] = Query(None, description="API tokens: the token's org slug"),
    status: Optional[str] = Query(None, description="One or more (comma-separated) of matched,partial,ambiguous,unrecognized,not_applicable"),
    level: Optional[str] = Query(None, description="national | regional | local"),
    department: Optional[str] = Query(None, description="canonical department key, e.g. tabligh"),
    region: Optional[str] = Query(None, description="canonical region name, e.g. Northeast"),
    majlis: Optional[str] = Query(None, description="canonical Majlis name, e.g. Albany"),
    q: Optional[str] = Query(None, max_length=100, description="substring of the seen email"),
    has_override: Optional[bool] = Query(None),
    mismatch: Optional[bool] = Query(None, description="self-reported Majlis differs from the derived one"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=svc.MAX_PAGE_SIZE),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Effective + derived + override per user, filtered and paginated. Org-scoped."""
    admin = await _resolve_admin(current_user, org_id, org_slug, db_session, allow_token=True)
    return await svc.list_attributes(
        db_session,
        admin.org_id,
        filters={
            "status": _csv(status), "level": level, "department": department,
            "region": region, "majlis": majlis,
        },
        q=q, has_override=has_override, mismatch=mismatch, page=page, page_size=page_size,
        redact=isinstance(current_user, APITokenUser), token_view=isinstance(current_user, APITokenUser),
    )


@router.get("/review-queue")
async def api_review_queue(
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=svc.MAX_PAGE_SIZE),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """"Needs review": unrecognized / ambiguous / partial accounts, plus the
    Majlis-mismatch set (self-reported vs derived)."""
    admin = await _resolve_admin(current_user, org_id, org_slug, db_session)
    unclassified = await svc.list_attributes(
        db_session, admin.org_id, filters={"status": REVIEW_STATUSES}, page=page, page_size=page_size
    )
    mismatched = await svc.list_attributes(
        db_session, admin.org_id, mismatch=True, page=page, page_size=page_size
    )
    return {"unclassified": unclassified, "mismatch": mismatched}


@router.get("/users/{user_id}")
async def api_get_user(
    user_id: int,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    admin = await _resolve_admin(current_user, org_id, org_slug, db_session)
    user = await _target_user(admin, user_id, db_session)
    view = await svc.get_admin_view(db_session, user, admin.org_id)
    if view is None:
        raise HTTPException(status_code=404, detail="No attributes derived for this user yet")
    return view


@router.get("/users/{user_id}/audit")
async def api_get_user_audit(
    user_id: int,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    admin = await _resolve_admin(current_user, org_id, org_slug, db_session)
    await _target_user(admin, user_id, db_session)
    if await svc.is_shared_with_other_orgs(db_session, user_id, admin.org_id):
        # The audit trail is global: another org's admin notes are not visible from here.
        raise HTTPException(status_code=403, detail="Audit history is not available for users shared across organizations")
    return {"items": await svc.list_audit(db_session, user_id, limit)}


# ---------------------------------------------------------------------------
# admin: per-user override (session admins only)
# ---------------------------------------------------------------------------

async def _override_admin(
    current_user, user_id: int, org_id: Optional[int], org_slug: Optional[str], db_session: AsyncSession
) -> tuple[_Admin, User]:
    if isinstance(current_user, (APITokenUser, SuperadminAPITokenUser)):
        raise HTTPException(status_code=403, detail="A user session is required")
    admin = await _resolve_admin(current_user, org_id, org_slug, db_session)
    # Attributes are one global row per user: the service refuses (409) any write whose target
    # belongs to an org other than the admin's (assert_exclusive_to_org).
    user = await _target_user(admin, user_id, db_session)
    return admin, user


@router.put("/users/{user_id}/override")
async def api_put_override(
    user_id: int,
    body: OverrideIn,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Set the admin override (partial attributes) with a REQUIRED reason; audited."""
    admin, user = await _override_admin(current_user, user_id, org_id, org_slug, db_session)
    try:
        await svc.set_override(db_session, user, body.override, body.reason, admin.actor_user_id, admin.org_id)  # type: ignore[arg-type]
    except ValueError as exc:
        raise _bad_request(exc)
    except svc.CrossOrgConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return await svc.get_admin_view(db_session, user, admin.org_id)  # type: ignore[return-value]


@router.delete("/users/{user_id}/override")
async def api_delete_override(
    user_id: int,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    reason: Optional[str] = Query(None, max_length=1000),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    admin, user = await _override_admin(current_user, user_id, org_id, org_slug, db_session)
    try:
        await svc.clear_override(db_session, user, admin.actor_user_id, reason, admin.org_id)  # type: ignore[arg-type]
    except svc.CrossOrgConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    view = await svc.get_admin_view(db_session, user, admin.org_id)
    if view is None:
        raise HTTPException(status_code=404, detail="No attributes derived for this user yet")
    return view


# ---------------------------------------------------------------------------
# admin: roster overrides (per email; usable by the companion service's token)
# ---------------------------------------------------------------------------

def _roster_view(row: MkaRosterOverride) -> dict:
    return {
        "org_id": row.org_id, "email": row.email, "attributes": row.attributes, "source": row.source, "note": row.note,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": row.updated_by,
    }


@router.get("/roster")
async def api_list_roster(
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    admin = await _resolve_admin(current_user, org_id, org_slug, db_session, allow_token=True)
    rows = (
        await db_session.execute(
            select(MkaRosterOverride).where(MkaRosterOverride.org_id == admin.org_id).order_by(MkaRosterOverride.email)  # type: ignore[arg-type]
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return {"items": [_roster_view(r) for r in rows], "page": page, "page_size": page_size}


@router.post("/roster/import")
async def api_import_roster(
    body: RosterImportIn,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Bulk roster upsert (<= 1000 rows). One bad row never aborts the batch: each row
    gets ``ok`` / ``error``. ``dry_run`` validates without writing."""
    admin = await _resolve_admin(current_user, org_id, org_slug, db_session, allow_token=True, token_right=TOKEN_WRITE_FULL)
    return await svc.import_roster(
        db_session, admin.org_id,
        [r.model_dump() for r in body.rows],
        source=admin.source, actor_user_id=admin.actor_user_id, dry_run=body.dry_run,
    )


@router.put("/roster/{email}")
async def api_put_roster(
    email: str,
    body: RosterIn,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    admin = await _resolve_admin(current_user, org_id, org_slug, db_session, allow_token=True, token_right=TOKEN_WRITE_FULL)
    try:
        row = await svc.upsert_roster(
            db_session, admin.org_id, email, body.attributes, source=admin.source, note=body.note,
            actor_user_id=admin.actor_user_id,
        )
    except ValueError as exc:
        raise _bad_request(exc)
    except svc.CrossOrgConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _roster_view(row)


@router.delete("/roster/{email}")
async def api_delete_roster(
    email: str,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    admin = await _resolve_admin(current_user, org_id, org_slug, db_session, allow_token=True, token_right=TOKEN_WRITE_FULL)
    try:
        deleted = await svc.delete_roster(db_session, admin.org_id, email, admin.actor_user_id)
    except svc.CrossOrgConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="No roster override for that email")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# admin: recompute
# ---------------------------------------------------------------------------

@router.post("/recompute")
async def api_recompute(
    body: RecomputeIn,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Recompute the org's members' attributes now (synchronous, batched; idempotent:
    audit rows only where the derived value changed). Overrides are never touched."""
    admin = await _resolve_admin(current_user, org_id, org_slug, db_session)
    return await svc.recompute_users(
        db_session, org_id=admin.org_id,
        actor_user_id=admin.actor_user_id, dry_run=body.dry_run,
    )
