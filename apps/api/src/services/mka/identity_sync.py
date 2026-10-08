"""MKA fork: identity sync, Mohtamim role + managed user groups from role mailboxes (spec 2026-10-07 section 3.A).

What it does, for an org member whose MKA identity attributes are PROVEN and CURRENT:

* groups: the person is a member of every managed group their attributes imply (``majlis:<slug>``, ``region:<slug>``,
  ``department:<slug>``, ``level:national|regional|local``) and of no other MANAGED group. Groups that are not in
  ``mka_managed_group`` are never touched;
* role: a national Mohtamim / Naib Mohtamim holding the default learner role (id 4) is moved to the managed
  ``Mohtamim`` role; a holder of that managed role whose attributes no longer qualify is moved back to 4. Role ids
  1, 2, 3 and every other custom role are never changed. The role-change email is NOT sent.

Contract (same style as ``automation_enroll``):

* flag ``MKA_IDENTITY_SYNC_ENABLED`` (default false) is read at CALL time; disabled = ZERO writes;
* the login entry point ``identity_sync_user`` runs in its OWN session, never raises (fail-open for login) and is
  bounded by a timeout;
* the ``is_address_proven`` gate applies: an unproven or stale identity is skipped and nothing is removed;
* idempotent: a second run with the same attributes performs zero writes (reads only);
* writes go straight to the tables (the HTTP-facing services need a request and an acting user, which a login hook and
  an org-token backfill do not have). The ``usergroups`` usage counter and the ``usergroup_created`` webhook are
  therefore not fired for managed groups.
"""

from __future__ import annotations

import asyncio
import logging
import os
import weakref
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable, Optional
from uuid import uuid4

from sqlalchemy import delete, or_, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.mka_identity import MkaIdentitySyncState, MkaManagedGroup, MkaManagedRole
from src.db.mka_user_attributes import MkaUserAttributes
from src.db.mka_user_profile import MkaUserProfile
from src.db.roles import (
    DashboardPermission,
    Permission,
    PermissionsWithOwn,
    Rights,
    Role,
    RoleTypeEnum,
)
from src.db.user_organizations import UserOrganization
from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup
from src.db.users import User
from src.services.mka import attributes as attrs
from src.services.mka.identity_parser import IdentityRules, slugify_majlis

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15.0
DEFAULT_ROLE_ID = 4  # the global "User" role Google SSO assigns on first join
MOHTAMIM_KEY = "mohtamim"
MOHTAMIM_ROLE_NAME = "Mohtamim"
MOHTAMIM_ROLE_DESCRIPTION = "MKA department head: creates and runs courses for their department"
MOHTAMIM_ROLES = ("mohtamim", "naib_mohtamim")
# Bump when MOHTAMIM_RIGHTS changes: ``ensure_org`` rewrites the role's rights ONCE per version (an admin's later edits
# in the UI survive until the next bump).
MOHTAMIM_RIGHTS_VERSION = 2  # 2: media/folders narrowed to create+read (no update/delete)
GROUP_DESCRIPTION = "Managed by MKA identity sync; membership follows the role mailbox"
LEVEL_GROUPS = {"national": "National Amila", "regional": "Regional Amila", "local": "Local Amila"}
EXCLUDED_DEPARTMENTS = frozenset({"atfal"})  # like the compliance roster; departments with has_course=false are skipped too
PLAN_ROWS_CAP = 200
BATCH = 500


def enabled() -> bool:
    """``MKA_IDENTITY_SYNC_ENABLED`` (default false), read at call time."""
    return os.environ.get("MKA_IDENTITY_SYNC_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def allowed_org_ids() -> frozenset[int]:
    """``MKA_IDENTITY_SYNC_ORG_IDS``: comma-separated org ids the sync may WRITE in. Unset / empty = no org (fail closed:
    the platform is multi-tenant and the managed role/groups must never appear in an org nobody opted in)."""
    out: set[int] = set()
    for part in os.environ.get("MKA_IDENTITY_SYNC_ORG_IDS", "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            logger.warning("MKA identity sync: ignoring a non-numeric entry in MKA_IDENTITY_SYNC_ORG_IDS")
    return frozenset(out)


def org_allowed(org_id: int) -> bool:
    return org_id in allowed_org_ids()


class OrgNotAllowed(Exception):
    """A write was requested for an org that is not in ``MKA_IDENTITY_SYNC_ORG_IDS``."""


def _now() -> str:
    return str(datetime.now())


# ---------------------------------------------------------------------------------------------------------------
# role definition
# ---------------------------------------------------------------------------------------------------------------

def _crud(c=False, r=False, u=False, d=False) -> Permission:
    return Permission(action_create=c, action_read=r, action_update=u, action_delete=d)


def _own(c=False, r=False, ro=False, u=False, uo=False, d=False, do=False) -> PermissionsWithOwn:
    return PermissionsWithOwn(
        action_create=c, action_read=r, action_read_own=ro, action_update=u, action_update_own=uo,
        action_delete=d, action_delete_own=do,
    )


def mohtamim_rights() -> dict:
    """Instructor's rights plus authoring depth (spec A1). No ``users`` / ``roles`` / org update, and no update or delete
    of courses the person did not create or does not actively co-author (the ``*_own`` flags, same as Instructor)."""
    own_all = _own(c=True, r=True, ro=True, uo=True, do=True)
    rights = Rights(
        courses=_own(c=True, r=True, ro=True, uo=True, do=True),
        users=_crud(),
        usergroups=_crud(r=True),
        folders=_crud(True, True),  # create + read only: update/delete would reach every org member's media (security review)
        media=_crud(True, True),
        organizations=_crud(r=True),
        coursechapters=_crud(True, True, True),
        activities=_crud(True, True, True),
        assignments=_crud(True, True, True),
        roles=_crud(),
        dashboard=DashboardPermission(action_access=True),
        communities=_crud(r=True),
        discussions=own_all,
        podcasts=own_all,
        boards=own_all,
        playgrounds=own_all,
    )
    return rights.model_dump()


# ---------------------------------------------------------------------------------------------------------------
# group catalogue
# ---------------------------------------------------------------------------------------------------------------

def region_slugs(rules: IdentityRules) -> dict[str, str]:
    """Region display name -> group slug for EVERY region value of ``MAJLIS_TO_REGION`` (the source the profile writes
    ``region`` from), so the two cannot drift. The rules file's slugs win; a region it omits (Muqami) gets its slugified name."""
    out = {name: slug for slug, name in rules.regions.items()}
    for name in set(rules.majlis_to_region.values()):
        out.setdefault(name, slugify_majlis(name))
    return out


def catalogue(rules: Optional[IdentityRules] = None) -> dict[str, str]:
    """Managed group key -> display name. Majlis come from ``MAJLIS_TO_REGION`` (via the rules object), regions and
    departments from the identity rules file: one source each, nothing hardcoded here."""
    rules = rules or attrs.get_rules()
    out: dict[str, str] = {}
    for name in sorted(rules.majlis_to_region):
        out[f"majlis:{slugify_majlis(name)}"] = f"Majlis: {name}"
    for name, slug in sorted(region_slugs(rules).items()):  # incl. regions the rules file omits (Muqami)
        out[f"region:{slug}"] = f"Region: {name}"
    no_course = {d["key"] for d in rules.raw.get("departments", []) if d.get("has_course") is False}
    for key, name in rules.department_names.items():
        if key in EXCLUDED_DEPARTMENTS or key in no_course:
            continue
        out[f"department:{key}"] = f"Department: {name}"
    for level, name in LEVEL_GROUPS.items():
        out[f"level:{level}"] = name
    return out


def desired_group_keys(effective: dict, cat: dict[str, str], rules: Optional[IdentityRules] = None) -> set[str]:
    """The managed groups the effective attributes imply (only keys that exist in the catalogue)."""
    rules = rules or attrs.get_rules()
    keys: set[str] = set()
    if effective.get("majlis"):
        keys.add(f"majlis:{slugify_majlis(str(effective['majlis']))}")
    if effective.get("region"):
        slug = region_slugs(rules).get(str(effective["region"]))
        if slug:
            keys.add(f"region:{slug}")
    if effective.get("department"):
        keys.add(f"department:{effective['department']}")
    if effective.get("is_officeholder") is True and effective.get("level") in LEVEL_GROUPS:
        keys.add(f"level:{effective['level']}")
    return {k for k in keys if k in cat}


def profile_group_keys(profile: Any, cat: dict[str, str], rules: Optional[IdentityRules] = None) -> set[str]:
    """Managed groups a member's profile implies: its Majlis and Region only (no department / level)."""
    return desired_group_keys({"majlis": profile.majlis, "region": profile.region}, cat, rules)


def desired_groups(trust: Optional["Trust"], profile: Any, cat: dict[str, str], rules: Optional[IdentityRules] = None) -> Optional[set[str]]:
    """THE rule for a user's managed groups, used by every path (login, profile save, backfill):

    * trusted (proven, current) officeholder -> the mailbox-derived set, with gaps filled from the profile field by field:
      a mailbox that gives no Majlis (regional / national) gets the profile's Majlis, one that gives no Region (national)
      gets the profile's Region. A value the mailbox DOES give always wins;
    * otherwise a profile row -> its Majlis + Region groups;
    * otherwise a trusted non-officeholder -> empty (nothing implies a group);
    * an untrusted identity with no profile -> ``None``: leave the groups alone (nothing to base a decision on)."""
    if trust is not None and trust.effective.get("is_officeholder") is True:
        eff = dict(trust.effective)
        if profile is not None:
            if not eff.get("majlis"):
                eff["majlis"] = profile.majlis
            if not eff.get("region"):
                eff["region"] = profile.region
        return desired_group_keys(eff, cat, rules)
    if profile is not None:
        return profile_group_keys(profile, cat, rules)
    return set() if trust is not None else None


def qualifies_for_mohtamim_role(effective: dict) -> bool:
    return (
        effective.get("is_officeholder") is True
        and effective.get("level") == "national"
        and effective.get("role") in MOHTAMIM_ROLES
    )


# ---------------------------------------------------------------------------------------------------------------
# org context: managed role + groups (ensure = create/update, idempotent)
# ---------------------------------------------------------------------------------------------------------------

@dataclass
class OrgCtx:
    org_id: int
    role_id: Optional[int] = None  # None only in dry-run when the role does not exist yet
    groups: dict[str, Optional[int]] = field(default_factory=dict)  # key -> usergroup id (None = would be created)
    role_created: bool = False
    role_updated: bool = False
    groups_created: int = 0
    groups_recreated: int = 0  # bound key whose usergroup was deleted (e.g. in the UI): same key, new group
    stale_keys: set[str] = field(default_factory=set)

    @property
    def key_by_gid(self) -> dict[int, str]:
        return {gid: k for k, gid in self.groups.items() if gid is not None}


_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, list[asyncio.Lock]]" = weakref.WeakKeyDictionary()
_STRIPES = 64


def _lock_for(*parts: Any) -> asyncio.Lock:
    stripes = _LOCKS.setdefault(asyncio.get_running_loop(), [asyncio.Lock() for _ in range(_STRIPES)])
    return stripes[hash(parts) % _STRIPES]


async def _pg_lock(db: AsyncSession, key: str) -> None:
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": key})


async def _sync_pg_sequence(db: AsyncSession, table: str) -> None:
    """Move ``<table>.id``'s sequence past MAX(id). ``setup.install_default_elements`` seeds the global roles with EXPLICIT
    ids 1-4 and never advances the sequence, so the first sequence-assigned ``Role`` insert would collide with the
    seeded Admin role (UniqueViolation on ``role_pkey``). Never moves the sequence backwards. No-op off Postgres."""
    if db.get_bind().dialect.name != "postgresql":
        return
    seq = (await db.execute(text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": table})).scalar()
    if not seq:
        return
    top = (await db.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}"))).scalar() or 0  # noqa: S608 (fixed table names)
    last, called = (await db.execute(text(f"SELECT last_value, is_called FROM {seq}"))).one()  # noqa: S608 (name from the catalog)
    next_free = last + 1 if called else last
    if top >= next_free:
        await db.execute(text("SELECT setval(CAST(:s AS regclass), :v, true)"), {"s": seq, "v": top})


async def _read_ctx(db: AsyncSession, org_id: int, cat: dict[str, str]) -> tuple[OrgCtx, Optional[MkaManagedRole], Optional[Role]]:
    binding = (
        await db.execute(
            select(MkaManagedRole)
            .where(MkaManagedRole.org_id == org_id, MkaManagedRole.key == MOHTAMIM_KEY)
            .execution_options(populate_existing=True)
        )
    ).scalars().first()
    role = await db.get(Role, binding.role_id, populate_existing=True) if binding is not None else None
    if role is not None and role.org_id != org_id:
        role = None
    ctx = OrgCtx(org_id=org_id, role_id=role.id if role is not None else None)
    rows = (
        await db.execute(
            select(MkaManagedGroup.key, MkaManagedGroup.usergroup_id)
            .join(UserGroup, UserGroup.id == MkaManagedGroup.usergroup_id)  # type: ignore[arg-type]
            .where(MkaManagedGroup.org_id == org_id, UserGroup.org_id == org_id)
        )
    ).all()
    present = {k: gid for k, gid in rows if k in cat}
    bound = set(
        (await db.execute(select(MkaManagedGroup.key).where(MkaManagedGroup.org_id == org_id))).scalars().all()
    )
    ctx.stale_keys = {k for k in bound if k in cat and k not in present}
    ctx.groups = {k: present.get(k) for k in cat}
    return ctx, binding, role


def _needs_writes(ctx: OrgCtx, binding: Optional[MkaManagedRole]) -> bool:
    return (
        ctx.role_id is None
        or binding is None
        or binding.rights_version != MOHTAMIM_RIGHTS_VERSION
        or any(gid is None for gid in ctx.groups.values())
    )


async def ensure_org(db: AsyncSession, org_id: int, *, dry_run: bool = False) -> OrgCtx:
    """Create / update the managed role and groups of ``org_id``. Zero writes when everything is present and current.
    ``dry_run`` reports what WOULD be created (``role_created`` / ``groups_created``) and never writes."""
    cat = catalogue()
    ctx, binding, role = await _read_ctx(db, org_id, cat)
    if not _needs_writes(ctx, binding):
        return ctx
    if dry_run:
        ctx.role_created = ctx.role_id is None
        ctx.role_updated = ctx.role_id is not None and (binding is None or binding.rights_version != MOHTAMIM_RIGHTS_VERSION)
        missing = [k for k, gid in ctx.groups.items() if gid is None]
        ctx.groups_recreated = sum(1 for k in missing if k in ctx.stale_keys)
        ctx.groups_created = len(missing) - ctx.groups_recreated
        return ctx
    if not org_allowed(org_id):
        raise OrgNotAllowed(org_id)

    async with _lock_for("ensure", org_id):
        await _pg_lock(db, f"mka-identity:ensure:{org_id}")  # READ COMMITTED: the re-read below sees what a rival committed
        ctx, binding, role = await _read_ctx(db, org_id, cat)
        if not _needs_writes(ctx, binding):
            return ctx
        now = _now()
        await _sync_pg_sequence(db, "role")
        await _sync_pg_sequence(db, "usergroup")

        # --- role ---
        if role is None:
            role = (
                await db.execute(  # adopt an org role an admin already named "Mohtamim" instead of creating a 409 duplicate
                    select(Role).where(
                        Role.org_id == org_id, Role.role_type == RoleTypeEnum.TYPE_ORGANIZATION,
                        Role.name == MOHTAMIM_ROLE_NAME,
                    )
                )
            ).scalars().first()
            if role is None:
                role = Role(
                    name=MOHTAMIM_ROLE_NAME, description=MOHTAMIM_ROLE_DESCRIPTION, org_id=org_id,
                    role_type=RoleTypeEnum.TYPE_ORGANIZATION, role_uuid=f"role_{uuid4()}",
                    rights=mohtamim_rights(), creation_date=now, update_date=now,
                )
                db.add(role)
                await db.flush()
                ctx.role_created = True
            else:
                role.rights = mohtamim_rights()
                role.update_date = now
                db.add(role)
                ctx.role_updated = True
            await db.execute(delete(MkaManagedRole).where(MkaManagedRole.org_id == org_id, MkaManagedRole.key == MOHTAMIM_KEY))
            db.add(MkaManagedRole(org_id=org_id, key=MOHTAMIM_KEY, role_id=role.id, rights_version=MOHTAMIM_RIGHTS_VERSION))  # type: ignore[arg-type]
        elif binding is not None and binding.rights_version != MOHTAMIM_RIGHTS_VERSION:
            role.rights = mohtamim_rights()
            role.update_date = now
            db.add(role)
            binding.rights_version = MOHTAMIM_RIGHTS_VERSION
            db.add(binding)
            ctx.role_updated = True
        ctx.role_id = role.id

        # --- groups ---
        for key, gid in list(ctx.groups.items()):
            if gid is not None:
                continue
            group = UserGroup(
                name=cat[key], description=GROUP_DESCRIPTION, org_id=org_id,
                usergroup_uuid=f"usergroup_{uuid4()}", creation_date=now, update_date=now,
            )
            db.add(group)
            await db.flush()
            await db.execute(delete(MkaManagedGroup).where(MkaManagedGroup.org_id == org_id, MkaManagedGroup.key == key))
            db.add(MkaManagedGroup(org_id=org_id, key=key, usergroup_id=group.id))  # type: ignore[arg-type]
            ctx.groups[key] = group.id
            if key in ctx.stale_keys:
                ctx.groups_recreated += 1
                logger.info("MKA identity sync: recreated managed group %s in org %s", key, org_id)
            else:
                ctx.groups_created += 1
        await db.commit()
        return ctx


# ---------------------------------------------------------------------------------------------------------------
# per-user sync
# ---------------------------------------------------------------------------------------------------------------

@dataclass
class UserPlan:
    user_id: int
    skipped: Optional[str] = None  # 'no_attributes' | 'unproven' | 'stale' | 'not_member'
    add: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    role: Optional[str] = None  # 'set' | 'revert'
    membership: Any = field(default=None, repr=False, compare=False)

    @property
    def changed(self) -> bool:
        return bool(self.add or self.remove or self.role)

    def row(self) -> dict:
        return {"user_id": self.user_id, "add": list(self.add), "remove": list(self.remove), "role": self.role}


@dataclass
class Trust:
    effective: dict  # drives the groups (see _gate)
    role_attrs: dict  # drives the Mohtamim role (see _gate)


async def _gate(db: AsyncSession, user: Any) -> tuple[Optional[Trust], Optional[str]]:
    """COPIES of the attributes to trust, or the reason they cannot be trusted. Reads only. (Copies, because a later
    rollback expires the ORM row.)

    The ROLE AND GROUPS are decided from ``row.derived`` (the parser output for the proven mailbox) when the account belongs to more
    than one org, mirroring ``attributes.roster_for_user``: a roster or admin-override layer written for one org must
    never grant a role in another. A single-org account uses the effective attributes (override > roster > parser)."""
    row = await attrs.get_row(db, user.id)
    if row is None:
        return None, "no_attributes"
    if not attrs.is_address_proven(row, user):
        return None, "unproven"
    if attrs.is_stale(row, user):  # e.g. a rules-version bump awaiting recompute: reading it would look like "no groups"
        return None, "stale"
    effective = dict(row.effective or {})
    derived = dict(row.derived or {})
    n_orgs = len(set((await db.execute(select(UserOrganization.org_id).where(UserOrganization.user_id == user.id))).scalars().all()))
    trusted = derived if n_orgs > 1 else effective  # multi-org: nothing from an override/roster layer, for groups or role
    return Trust(effective=trusted, role_attrs=trusted), None


async def load_profile(db: AsyncSession, user_id: int) -> Optional[SimpleNamespace]:
    """A plain COPY of the member's profile (majlis, region) or None. Reads only."""
    row = (
        await db.execute(select(MkaUserProfile.majlis, MkaUserProfile.region).where(MkaUserProfile.user_id == user_id))
    ).first()
    return SimpleNamespace(majlis=row[0], region=row[1]) if row is not None else None


async def _sync_one(db: AsyncSession, ctx: OrgCtx, user: Any, trust: Optional[Trust], *, dry_run: bool,
                    profile: Any = None) -> UserPlan:
    """``trust`` None = untrusted identity: it never wins the role (a held managed role is taken back) and its groups come
    from the profile alone (the caller only gets here when there is one)."""
    if not dry_run and not org_allowed(ctx.org_id):
        raise OrgNotAllowed(ctx.org_id)
    plan = UserPlan(user_id=user.id)
    cat_keys = set(ctx.groups)
    desired = desired_groups(trust, profile, {k: k for k in cat_keys})
    wants_role = trust is not None and qualifies_for_mohtamim_role(trust.role_attrs)

    async def compute() -> UserPlan:
        p = UserPlan(user_id=user.id)
        membership = (
            await db.execute(
                select(UserOrganization)
                .where(UserOrganization.user_id == user.id, UserOrganization.org_id == ctx.org_id)
                .execution_options(populate_existing=True)
            )
        ).scalars().first()
        if membership is None:
            p.skipped = "not_member"
            return p
        key_by_gid = ctx.key_by_gid
        current_ids: set[int] = set()
        if key_by_gid:
            current_ids = set(
                (
                    await db.execute(
                        select(UserGroupUser.usergroup_id).where(
                            UserGroupUser.user_id == user.id, UserGroupUser.org_id == ctx.org_id,
                            UserGroupUser.usergroup_id.in_(list(key_by_gid)),  # type: ignore[attr-defined]
                        )
                    )
                ).scalars().all()
            )
        current = {key_by_gid[g] for g in current_ids}
        if desired is not None:
            p.add = sorted(desired - current)
            p.remove = sorted(current - desired)
        if wants_role and membership.role_id == DEFAULT_ROLE_ID:
            p.role = "set"
        elif ctx.role_id is not None and membership.role_id == ctx.role_id and not wants_role:
            p.role = "revert"
        p.membership = membership
        return p

    async with _lock_for("user", user.id, ctx.org_id):
        plan = await compute()
        if dry_run or plan.skipped or not plan.changed:
            return plan  # reads only: the common login performs no write and takes no lock
        await _pg_lock(db, f"mka-identity:user:{user.id}:{ctx.org_id}")
        plan = await compute()  # re-read under the lock (another process may have synced this user meanwhile)
        if not plan.changed:
            return plan
        membership = plan.membership
        now = _now()
        for key in plan.add:
            db.add(UserGroupUser(usergroup_id=ctx.groups[key], user_id=user.id, org_id=ctx.org_id,  # type: ignore[arg-type]
                                 creation_date=now, update_date=now))
        if plan.remove:
            await db.execute(
                delete(UserGroupUser).where(
                    UserGroupUser.user_id == user.id, UserGroupUser.org_id == ctx.org_id,
                    UserGroupUser.usergroup_id.in_([ctx.groups[k] for k in plan.remove]),  # type: ignore[attr-defined]
                )
            )
        if plan.role == "set":
            membership.role_id = ctx.role_id
        elif plan.role == "revert":
            membership.role_id = DEFAULT_ROLE_ID
        if plan.role:
            membership.update_date = now
            db.add(membership)
        await db.commit()

    if plan.role:
        _invalidate_session(user.id)
    return plan


def _invalidate_session(user_id: int) -> None:
    """Same cache the role-change endpoint drops, so the new rights apply on the next request. Best effort."""
    try:
        from src.routers.users import _invalidate_session_cache

        _invalidate_session_cache(user_id)
    except Exception:  # noqa: BLE001
        logger.debug("MKA identity sync: session cache invalidation failed", exc_info=True)


async def _peek_ctx(db: AsyncSession, org_id: int) -> OrgCtx:
    """The org's managed role / groups as they ARE (never creates anything)."""
    return (await _read_ctx(db, org_id, catalogue()))[0]


async def _revert_only(db: AsyncSession, ctx: OrgCtx, user_id: int, *, dry_run: bool = False) -> UserPlan:
    """Fail-closed step for an identity that cannot be trusted right now (no row, unproven, stale, refresh failed): a
    holder of the org's managed role goes back to the default role. Groups are left alone; nothing is ever granted."""
    plan = UserPlan(user_id=user_id)
    if ctx.role_id is None:
        return plan

    async def compute() -> Optional[UserOrganization]:
        membership = (
            await db.execute(
                select(UserOrganization)
                .where(UserOrganization.user_id == user_id, UserOrganization.org_id == ctx.org_id)
                .execution_options(populate_existing=True)
            )
        ).scalars().first()
        plan.role = "revert" if membership is not None and membership.role_id == ctx.role_id else None
        return membership

    async with _lock_for("user", user_id, ctx.org_id):
        await compute()
        if dry_run or not plan.role:
            return plan
        if not org_allowed(ctx.org_id):
            raise OrgNotAllowed(ctx.org_id)
        await _pg_lock(db, f"mka-identity:user:{user_id}:{ctx.org_id}")
        membership = await compute()
        if not plan.role or membership is None:
            return plan
        membership.role_id = DEFAULT_ROLE_ID
        membership.update_date = _now()
        db.add(membership)
        await db.commit()
    _invalidate_session(user_id)
    return plan


async def sync_user_identity(db: AsyncSession, org_id: int, user: Any) -> UserPlan:
    """Sync ONE user in ONE org (spec A3). ``user`` is anything with ``id`` and ``email``. No writes when the flag is off,
    the org is not allowlisted, or nothing differs. An identity that cannot be trusted only ever LOSES the managed role.
    May raise: the login wrapper catches."""
    if not enabled():
        return UserPlan(user_id=user.id, skipped="disabled")
    if not org_allowed(org_id):
        return UserPlan(user_id=user.id, skipped="org_not_allowed")
    trust, reason = await _gate(db, user)
    profile = await load_profile(db, user.id)
    if trust is None and profile is None:
        plan = await _revert_only(db, await _peek_ctx(db, org_id), user.id)
        plan.skipped = reason
        return plan
    ctx = await ensure_org(db, org_id)
    return await _sync_one(db, ctx, user, trust, dry_run=False, profile=profile)


async def identity_sync_user(db_factory: Callable[[], AsyncSession], user: Any) -> None:
    """Login entry point. NEVER raises; own session (``db_factory()`` must return a NEW session)."""
    try:
        if not enabled():
            return
        await asyncio.wait_for(_run(db_factory, user), timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - fail-open for LOGIN by design (also covers the timeout)
        logger.error("MKA identity sync failed (login unaffected): %s", type(exc).__name__)  # no traceback: SQL params can hold PII


async def sync_member_groups(db_factory: Callable[[], AsyncSession], user_id: int) -> None:
    """Profile-save entry point (signup, self edit, admin edit): re-sync the user's managed groups in every allowlisted org
    they belong to, through the same ``_run`` as login. Own session, NEVER raises, flag off = zero writes."""
    try:
        if not enabled():
            return
        async with db_factory() as s:
            email = (await s.execute(select(User.email).where(User.id == user_id))).scalar()
        if email is None:
            return
        await asyncio.wait_for(_run(db_factory, SimpleNamespace(id=user_id, email=email)), timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - fail-open: a profile save never fails because of group sync
        logger.error("MKA member group sync failed (profile save unaffected): %s", type(exc).__name__)


async def _run(db_factory: Callable[[], AsyncSession], user: Any) -> None:
    async with db_factory() as s:
        org_ids = sorted(
            set((await s.execute(select(UserOrganization.org_id).where(UserOrganization.user_id == user.id))).scalars().all())
            & allowed_org_ids()
        )
        if not org_ids:
            return
        trust, _reason = await _gate(s, user)
        profile = await load_profile(s, user.id)
        for org_id in org_ids:
            try:
                if trust is None and profile is None:
                    await _revert_only(s, await _peek_ctx(s, org_id), user.id)
                    continue
                ctx = await ensure_org(s, org_id)
                plan = await _sync_one(s, ctx, user, trust, dry_run=False, profile=profile)
                if plan.changed:
                    logger.info("MKA identity sync: org %s user %s +%d -%d role=%s", org_id, user.id,
                                len(plan.add), len(plan.remove), plan.role)
            except Exception as exc:  # noqa: BLE001 - one org failing never blocks the next
                logger.error("MKA identity sync failed for one org (rolled back): %s", type(exc).__name__)
                try:
                    await s.rollback()
                except Exception:  # noqa: BLE001
                    pass


# ---------------------------------------------------------------------------------------------------------------
# backfill + status (A4)
# ---------------------------------------------------------------------------------------------------------------

async def backfill_org(db: AsyncSession, org_id: int, *, dry_run: bool = True) -> dict:
    """Ensure the role and groups, then sync every org member that has an attribute row OR a profile row. In ``dry_run`` nothing is
    written and ``planned`` lists the changes (user ids only, capped). Per-user failures are counted, not raised."""
    counts = {
        "users_seen": 0, "groups_created": 0, "groups_recreated": 0, "memberships_added": 0, "memberships_removed": 0,
        "roles_set": 0, "roles_reverted": 0, "errors": 0,
    }
    skipped: dict[str, int] = {}
    planned: list[dict] = []
    if not org_allowed(org_id):
        if not dry_run:
            raise OrgNotAllowed(org_id)
        # A preview of an org nobody opted in reveals nothing about its people: zero counts, no rows.
        return {**counts, "dry_run": True, "org_allowed": False, "role_created": False, "role_updated": False,
                "skipped": {}, "planned": [], "planned_truncated": False}
    ctx = await ensure_org(db, org_id, dry_run=dry_run)
    counts["groups_created"] = ctx.groups_created
    counts["groups_recreated"] = ctx.groups_recreated
    last_id = 0
    while True:
        rows = (
            await db.execute(
                select(User.id, User.email)
                .join(UserOrganization, UserOrganization.user_id == User.id)  # type: ignore[arg-type]
                .outerjoin(MkaUserAttributes, MkaUserAttributes.user_id == User.id)  # type: ignore[arg-type]
                .outerjoin(MkaUserProfile, MkaUserProfile.user_id == User.id)  # type: ignore[arg-type]
                .where(UserOrganization.org_id == org_id, User.id > last_id)  # type: ignore[arg-type]
                .where(or_(MkaUserAttributes.user_id.is_not(None), MkaUserProfile.user_id.is_not(None)))  # type: ignore[union-attr]
                .order_by(User.id)  # type: ignore[arg-type]
                .limit(BATCH)
            )
        ).all()
        if not rows:
            break
        last_id = rows[-1][0]
        for uid, email in rows:
            counts["users_seen"] += 1
            user = SimpleNamespace(id=uid, email=email)
            try:
                trust, reason = await _gate(db, user)
                profile = await load_profile(db, uid)
                if trust is None and profile is None:  # cannot be trusted: never grant, but a held managed role is taken back
                    skipped[reason or "skipped"] = skipped.get(reason or "skipped", 0) + 1
                    reverted = await _revert_only(db, ctx, uid, dry_run=dry_run)
                    counts["roles_reverted"] += reverted.role == "revert"
                    if dry_run and reverted.changed and len(planned) < PLAN_ROWS_CAP:
                        planned.append(reverted.row())
                    continue
                plan = await _sync_one(db, ctx, user, trust, dry_run=dry_run, profile=profile)
            except Exception as exc:  # noqa: BLE001
                counts["errors"] += 1
                logger.error("MKA identity backfill failed for one user: %s", type(exc).__name__)
                await db.rollback()
                continue
            if plan.skipped:
                skipped[plan.skipped] = skipped.get(plan.skipped, 0) + 1
                continue
            counts["memberships_added"] += len(plan.add)
            counts["memberships_removed"] += len(plan.remove)
            counts["roles_set"] += plan.role == "set"
            counts["roles_reverted"] += plan.role == "revert"
            if dry_run and plan.changed and len(planned) < PLAN_ROWS_CAP:
                planned.append(plan.row())
    # Holders of the managed role with NO attribute row at all (never signed in through the hook, or the row was deleted).
    if ctx.role_id is not None:
        orphans = (
            await db.execute(
                select(UserOrganization.user_id).where(
                    UserOrganization.org_id == org_id, UserOrganization.role_id == ctx.role_id,
                    UserOrganization.user_id.notin_(select(MkaUserAttributes.user_id)),  # type: ignore[attr-defined]
                    UserOrganization.user_id.notin_(select(MkaUserProfile.user_id)),  # type: ignore[attr-defined]  (profile users ran above)
                )
            )
        ).scalars().all()
        for uid in orphans:
            counts["users_seen"] += 1
            skipped["no_attributes"] = skipped.get("no_attributes", 0) + 1
            try:
                reverted = await _revert_only(db, ctx, uid, dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001
                counts["errors"] += 1
                logger.error("MKA identity backfill failed for one user: %s", type(exc).__name__)
                await db.rollback()
                continue
            counts["roles_reverted"] += reverted.role == "revert"
            if dry_run and reverted.changed and len(planned) < PLAN_ROWS_CAP:
                planned.append(reverted.row())
    result: dict = {
        **counts, "dry_run": dry_run, "org_allowed": org_allowed(org_id), "role_created": ctx.role_created, "role_updated": ctx.role_updated,
        "skipped": skipped,
    }
    if dry_run:
        result["planned"] = planned
        result["planned_truncated"] = (counts["memberships_added"] + counts["memberships_removed"]
                                       + counts["roles_set"] + counts["roles_reverted"]) > 0 and len(planned) >= PLAN_ROWS_CAP
    else:
        await _record_sync(db, org_id, {k: counts[k] for k in counts} | {"skipped": skipped})
    return result


async def _record_sync(db: AsyncSession, org_id: int, summary: dict) -> None:
    state = await db.get(MkaIdentitySyncState, org_id)
    if state is None:
        state = MkaIdentitySyncState(org_id=org_id)
    state.last_sync_at = datetime.now()
    state.last_counts = summary
    db.add(state)
    await db.commit()


async def status(db: AsyncSession, org_id: int) -> dict:
    """Flag state, managed role id, managed group count and the last APPLIED backfill (no secrets, no addresses)."""
    cat = catalogue()
    ctx, binding, _role = await _read_ctx(db, org_id, cat)
    state = await db.get(MkaIdentitySyncState, org_id)
    return {
        "enabled": enabled(),
        "org_allowed": org_allowed(org_id),
        "role_id": ctx.role_id,
        "role_rights_version": binding.rights_version if binding is not None else None,
        "role_rights_version_current": MOHTAMIM_RIGHTS_VERSION,
        "groups": sum(1 for gid in ctx.groups.values() if gid is not None),
        "groups_expected": len(cat),
        "last_sync_at": state.last_sync_at.isoformat() if state is not None and state.last_sync_at else None,
        "last_counts": state.last_counts if state is not None else None,
    }


__all__ = [
    "OrgNotAllowed", "allowed_org_ids", "backfill_org", "catalogue", "org_allowed", "desired_group_keys", "enabled", "ensure_org", "identity_sync_user",
    "mohtamim_rights", "qualifies_for_mohtamim_role", "status", "sync_member_groups", "sync_user_identity",
]
