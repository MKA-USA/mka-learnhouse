"""MKA fork: who may see which compliance data (spec section 1). ONE function, used by every read endpoint.

``resolve_scope`` returns a :class:`Scope`:

* ``all``  superadmin; org role admin/maintainer; a role carrying ``organizations.action_update``;
           org API token; or national-level attributes holder matching ``SCOPE_ALL_ATTRIBUTE_RULES``.
* ``filtered`` an attribute holder who answers for ONE unit (seam C, spec 2026-10-07): a Mohtamim / Naib Mohtamim sees their
           department, a regional Qaid / Naib their region, a Majlis Qaid / Naib their Majlis. Every read applies the
           filter to the expected-roster rows on the server (``Scope.roster_filter``); nobody outside the unit is returned.
* ``own``  ACTIVE CREATOR/MAINTAINER/CONTRIBUTOR author of at least one cycle course (and passing the upstream
           ``update`` check on it). Sees only those courses.
* ``none`` everyone else.

Security properties (each one has a test):
* the org is verified (membership) and every later query filters by it; a client-supplied ``org_id`` is never
  trusted without a membership check;
* API tokens get ``all`` for THEIR org only and never ``own`` (a token has no author identity);
* elevated access derived from attributes FAILS CLOSED: a stale / missing / non-matched attribute row grants
  nothing (``attributes.read_effective_from_row``);
* an out-of-scope course is indistinguishable from a non-existent one (404).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from fastapi import HTTPException, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.courses import Course
from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse
from src.db.organizations import Organization
from src.db.resource_authors import (
    ResourceAuthor,
    ResourceAuthorshipEnum,
    ResourceAuthorshipStatusEnum,
)
from src.db.roles import Role
from src.db.users import APITokenUser, SuperadminAPITokenUser, User
from src.security.org_auth import enforce_org_mfa, get_user_org
from src.security.rbac.constants import ADMIN_OR_MAINTAINER_ROLE_IDS
from src.security.rbac.rbac import authorization_verify_based_on_roles_and_authorship
from src.security.superadmin import is_user_superadmin
from src.services.admin.admin import _require_api_token, _resolve_org_slug
from src.services.mka import attributes as attrs
from src.services.mka.token_rights import TOKEN_READ, TOKEN_WRITE_FULL, token_may  # noqa: F401  (shared helper, W1a)

# UNCONFIRMED (owner to confirm before go-live): which attribute holders may see ALL cycle courses.
# A rule matches when every listed key equals the viewer's EFFECTIVE attribute (fail-closed read, status must be
# 'matched'). Every rule pins level == 'national' on purpose: roles like Sadr / Motamid also exist at Majlis
# level and a local Sadr must NOT see every region. Edit here; nothing else encodes this decision.
SCOPE_ALL_ATTRIBUTE_RULES: tuple[dict, ...] = (
    {"level": "national", "department": "aitmad"},  # National Aitmad / General Secretary (UNCONFIRMED)
    {"level": "national", "role": "sadr"},          # National Sadr (UNCONFIRMED)
    {"level": "national", "role": "motamid"},       # National Motamid (UNCONFIRMED)
)

# Seam C: attribute holders limited to ONE unit. A rule matches on the viewer's EFFECTIVE attributes (fail-closed read,
# status 'matched', address proven) when level and role match AND the attribute named by ``field`` is set (a Mohtamim
# without a department, a Majlis Qaid without a Majlis ... get nothing). Naib role names are accepted in every spelling the
# rules file might emit, so a rules bump never silently removes access (and never grants more: unknown roles match nothing).
SCOPE_FILTER_RULES: tuple[dict, ...] = (
    {"level": "national", "roles": frozenset({"mohtamim", "naib_mohtamim"}), "field": "department"},
    {"level": "regional", "roles": frozenset({
        "regional_qaid", "qaid", "naib_qaid", "regional_naib_qaid", "naib_regional_qaid", "naib_qaid_regional",
    }), "field": "region"},
    {"level": "local", "roles": frozenset({"qaid", "naib_qaid"}), "field": "majlis"},
)

FIELD_LABELS = {"department": "department", "region": "region", "majlis": "Majlis"}

AUTHOR_AUTHORSHIPS = (
    ResourceAuthorshipEnum.CREATOR,
    ResourceAuthorshipEnum.MAINTAINER,
    ResourceAuthorshipEnum.CONTRIBUTOR,
)


@dataclass(frozen=True)
class Scope:
    kind: str  # 'all' | 'filtered' | 'own' | 'none'
    org_id: int
    source: str  # why (audit/debug, never returned to clients): superadmin|token|admin_role|org_update_right|attributes|attribute_filter|author|none
    user_id: Optional[int] = None
    own_course_ids: frozenset = field(default_factory=frozenset)  # Course.id the viewer may see (kind == 'own')
    filter_field: Optional[str] = None  # kind == 'filtered': 'department' | 'region' | 'majlis'
    filter_value: Optional[str] = None

    @property
    def roster_filter(self) -> Optional[dict]:
        """The attribute filter every roster read must carry (``None`` = the whole roster)."""
        if self.kind == "filtered":  # fail closed: a half-built filter yields clauses that match nothing, never the whole roster
            return {self.filter_field or "": self.filter_value or ""}
        return None

    def allows(self, course_id: int) -> bool:
        if self.kind in ("all", "filtered"):  # a filtered viewer sees the courses; their ROWS are what is limited
            return True
        return self.kind == "own" and course_id in self.own_course_ids

    def allows_link(self, link: MkaComplianceCycleCourse) -> bool:
        """Course-level visibility: a department-filtered viewer sees the general course and their own department's."""
        if not self.allows(link.course_id):
            return False
        if self.kind == "filtered" and self.filter_field == "department":
            return link.kind == "general" or _same(link.department, self.filter_value)
        return True

    def legacy_scope(self) -> str:
        """The pre-seam-C ``scope`` string of /scope: ``filtered`` is reported as ``own`` (limited), never ``all``."""
        return "own" if self.kind == "filtered" else self.kind

    def filter_view(self) -> Optional[dict]:
        """What /scope tells the client about the filter (None when the viewer is not filtered)."""
        if self.kind != "filtered" or not self.filter_field:
            return None
        label_value = self.filter_value or ""
        return {
            "field": self.filter_field, "value": label_value, self.filter_field: label_value,
            "label": f"Your {FIELD_LABELS[self.filter_field]}: {label_value}",
        }


def _same(a: Optional[str], b: Optional[str]) -> bool:
    return (a or "").strip().casefold() == (b or "").strip().casefold() != ""


def _role_has_org_update(role: Optional[Role], org_id: int) -> bool:
    if role is None or not role.rights:
        return False
    if role.org_id is not None and role.org_id != org_id:
        return False
    rights = role.rights
    org_rights = rights.get("organizations") if isinstance(rights, dict) else getattr(rights, "organizations", None)
    if not org_rights:
        return False
    value = org_rights.get("action_update") if isinstance(org_rights, dict) else getattr(org_rights, "action_update", False)
    return bool(value)


def attributes_grant_all(effective: dict) -> bool:
    """Pure: does this EFFECTIVE (already fail-closed) attribute dict match a scope-all rule?"""
    if effective.get("status") != "matched":
        return False
    return any(all(effective.get(k) == v for k, v in rule.items()) for rule in SCOPE_ALL_ATTRIBUTE_RULES)


def attributes_filter(effective: dict) -> Optional[tuple[str, str]]:
    """Pure: ``(field, value)`` when this EFFECTIVE (already fail-closed) attribute dict answers for exactly one
    unit, else ``None``. Callers check ``attributes_grant_all`` first and ``is_address_proven`` as well."""
    if effective.get("status") != "matched":
        return None
    for rule in SCOPE_FILTER_RULES:
        if effective.get("level") != rule["level"] or effective.get("role") not in rule["roles"]:
            continue
        value = effective.get(rule["field"])
        if isinstance(value, str) and value.strip():
            return rule["field"], value.strip()
    return None


async def _resolve_org_id(org_id: Optional[int], org_slug: Optional[str], db: AsyncSession) -> int:
    if org_id is None and org_slug:
        org = (await db.execute(select(Organization).where(Organization.slug == org_slug))).scalars().first()
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        return org.id  # type: ignore[return-value]
    if org_id is None:
        raise HTTPException(status_code=422, detail="org_id (or org_slug) is required")
    return org_id


async def _own_course_ids(request: Request, uid: int, org_id: int, db: AsyncSession) -> frozenset:
    rows = (
        await db.execute(
            select(MkaComplianceCycleCourse.course_id, MkaComplianceCycleCourse.course_uuid)
            .join(Course, Course.id == MkaComplianceCycleCourse.course_id)
            .join(ResourceAuthor, ResourceAuthor.resource_uuid == MkaComplianceCycleCourse.course_uuid)
            .where(
                MkaComplianceCycleCourse.org_id == org_id,
                Course.org_id == org_id,
                ResourceAuthor.user_id == uid,
                ResourceAuthor.authorship_status == ResourceAuthorshipStatusEnum.ACTIVE,
                ResourceAuthor.authorship.in_(AUTHOR_AUTHORSHIPS),  # type: ignore[attr-defined]
            )
            .distinct()
        )
    ).all()
    allowed = set()
    for course_id, course_uuid in rows:
        try:
            # The same check the course page tab uses (`update` permission): ACTIVE author / admin role.
            await authorization_verify_based_on_roles_and_authorship(request, uid, "update", course_uuid, db)
        except HTTPException:
            continue
        allowed.add(course_id)
    return frozenset(allowed)


async def resolve_scope(
    request: Request,
    current_user,
    org_id: Optional[int],
    org_slug: Optional[str],
    db: AsyncSession,
) -> Scope:
    """The single scope decision. Raises 403/404/422 for unauthenticated / non-member / bad-org callers."""
    # --- API tokens: all, for the token's own org only -------------------------------------------------
    if isinstance(current_user, APITokenUser):
        if not org_slug:
            raise HTTPException(status_code=422, detail="org_slug is required for API-token access")
        token_user = _require_api_token(current_user)
        token_may(token_user, *TOKEN_READ)
        org = await _resolve_org_slug(org_slug, token_user, db)  # 404 / 403 on other orgs, plan gate
        return Scope("all", org.id, "token")  # type: ignore[arg-type]
    if isinstance(current_user, SuperadminAPITokenUser):
        raise HTTPException(status_code=403, detail="Use an organization API token")

    uid = getattr(current_user, "id", None)
    if not uid:
        raise HTTPException(status_code=403, detail="A user session is required")
    resolved_org = await _resolve_org_id(org_id, org_slug, db)

    # --- superadmin -------------------------------------------------------------------------------------
    if await is_user_superadmin(uid, db):
        if await db.get(Organization, resolved_org) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        return Scope("all", resolved_org, "superadmin", uid)

    # --- org membership is mandatory for everyone else --------------------------------------------------
    membership = await get_user_org(uid, resolved_org, db)
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    await enforce_org_mfa(uid, resolved_org, db)

    if membership.role_id in ADMIN_OR_MAINTAINER_ROLE_IDS:
        return Scope("all", resolved_org, "admin_role", uid)
    role = (await db.execute(select(Role).where(Role.id == membership.role_id))).scalars().first()
    if _role_has_org_update(role, resolved_org):
        return Scope("all", resolved_org, "org_update_right", uid)

    user = await db.get(User, uid)
    if user is not None:
        row = await attrs.get_row(db, uid)
        effective, _stale = attrs.read_effective_from_row(row, user)  # fails closed
        # A roster/override row can set attributes for ANY address, so it must never grant `all` by itself: the account's
        # CURRENT address must also carry real Workspace/Google proof (M1 of the final review).
        if attributes_grant_all(effective) and attrs.is_address_proven(row, user):
            return Scope("all", resolved_org, "attributes", uid)
        unit = attributes_filter(effective)
        if unit is not None and attrs.is_address_proven(row, user):
            return Scope("filtered", resolved_org, "attribute_filter", uid, filter_field=unit[0], filter_value=unit[1])

    own = await _own_course_ids(request, uid, resolved_org, db)
    if own:
        return Scope("own", resolved_org, "author", uid, own)
    return Scope("none", resolved_org, "none", uid)


# ---------------------------------------------------------------------------------------------------------
# cycle / course resolution (always org-scoped)
# ---------------------------------------------------------------------------------------------------------

async def get_cycle(
    db: AsyncSession, org_id: int, cycle_id: Optional[int], today: Optional[str] = None
) -> Optional[MkaComplianceCycle]:
    """The requested cycle (404 when it is not this org's), else the DEFAULT cycle: the one whose
    [starts_on, deadline_on] window contains ``today``; else the most recent that has already started; else the
    newest (so importing next year's cycle early never switches the default)."""
    if cycle_id is not None:
        cycle = (
            await db.execute(
                select(MkaComplianceCycle).where(MkaComplianceCycle.id == cycle_id, MkaComplianceCycle.org_id == org_id)
            )
        ).scalars().first()
        if cycle is None:
            raise HTTPException(status_code=404, detail="Cycle not found")
        return cycle
    cycles = await all_cycles(db, org_id)  # newest first
    if not cycles:
        return None
    if today:
        day = date.fromisoformat(today)
        for c in cycles:
            if c.starts_on <= day <= c.deadline_on:
                return c
        for c in cycles:
            if c.starts_on <= day:
                return c
    return cycles[0]


async def cycle_courses(db: AsyncSession, org_id: int, cycle_id: int) -> list[tuple[MkaComplianceCycleCourse, Course]]:
    """All courses of a cycle (org filtered on BOTH the link row and the course)."""
    rows = (
        await db.execute(
            select(MkaComplianceCycleCourse, Course)
            .join(Course, Course.id == MkaComplianceCycleCourse.course_id)
            .where(
                MkaComplianceCycleCourse.cycle_id == cycle_id,
                MkaComplianceCycleCourse.org_id == org_id,
                Course.org_id == org_id,
            )
            .order_by(MkaComplianceCycleCourse.kind, MkaComplianceCycleCourse.department, MkaComplianceCycleCourse.id)  # type: ignore[arg-type]
        )
    ).all()
    return [(cc, course) for cc, course in rows]


def visible_courses(scope: Scope, rows: list[tuple[MkaComplianceCycleCourse, Course]]):
    if scope.kind == "none":
        return []
    return [(cc, c) for cc, c in rows if scope.allows_link(cc)]


def require_viewer(scope: Scope) -> None:
    """403 for viewers with no access at all."""
    if scope.kind == "none":
        raise HTTPException(status_code=403, detail="Compliance access required")


def require_all(scope: Scope) -> None:
    if scope.kind != "all":
        raise HTTPException(status_code=403, detail="Organization-wide compliance access required")


def require_overview(scope: Scope) -> None:
    """The overview needs a whole-org view (``all``) or a filtered one (its rows are limited server-side)."""
    if scope.kind not in ("all", "filtered"):
        raise HTTPException(status_code=403, detail="Organization-wide compliance access required")


def uuid_candidates(course_uuid: str) -> list[str]:
    """LearnHouse course uuids are ``course_<uuid>``; accept the bare uuid too."""
    return [course_uuid] if course_uuid.startswith("course_") else [course_uuid, f"course_{course_uuid}"]


async def all_cycles(db: AsyncSession, org_id: int) -> list[MkaComplianceCycle]:
    return list((await db.execute(
        select(MkaComplianceCycle).where(MkaComplianceCycle.org_id == org_id)
        .order_by(MkaComplianceCycle.starts_on.desc(), MkaComplianceCycle.id.desc())  # type: ignore[attr-defined]
    )).scalars().all())


async def resolve_course(
    db: AsyncSession, scope: Scope, cycle: Optional[MkaComplianceCycle], course_uuid: str
) -> tuple[MkaComplianceCycleCourse, Course]:
    """The cycle course for a viewer, or 404 (same answer for 'missing', 'other org', 'not yours')."""
    require_viewer(scope)
    not_found = HTTPException(status_code=404, detail="Course not found")
    if cycle is None:
        raise not_found
    row = (
        await db.execute(
            select(MkaComplianceCycleCourse, Course)
            .join(Course, Course.id == MkaComplianceCycleCourse.course_id)
            .where(
                MkaComplianceCycleCourse.cycle_id == cycle.id,
                MkaComplianceCycleCourse.org_id == scope.org_id,
                MkaComplianceCycleCourse.course_uuid.in_(uuid_candidates(course_uuid)),  # type: ignore[attr-defined]
                Course.org_id == scope.org_id,
            )
        )
    ).first()
    if row is None or not scope.allows_link(row[0]):
        raise not_found
    return row[0], row[1]
