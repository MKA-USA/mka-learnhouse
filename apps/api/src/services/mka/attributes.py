"""MKA fork: identity-attribute store + service (spec A2, A5, A7, A9).

Effective attributes = admin override > roster override (per email) > parser.
Recompute is a pure function of (email, rules, roster, override), so running it
twice gives the same result: a row is only written (and audited) when something
actually changed. Overrides are never touched by recompute.

Nothing here is writable by a user. The only user-facing read is
``effective_public`` (the viewer's own values, minus source/flag metadata).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Iterable, Optional

from sqlalchemy import and_, delete, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.mka_user_attributes import (
    MkaRosterOverride,
    MkaUserAttributes,
    MkaUserAttributesAudit,
)
from src.db.user_organizations import UserOrganization
from src.db.users import User
from src.security.session_context import AUTH_METHOD_GOOGLE
from src.services.mka.identity_parser import (
    LEVELS,
    STATUSES,
    IdentityRules,
    load_rules,
    parse_identity,
)
from src.services.auth.mka_google_only import is_google_only_email, take_verified_hd
from src.services.users.mka_profile import MAJLIS_TO_REGION

logger = logging.getLogger(__name__)

# Attribute fields an override / roster layer may set (never `source` or `flags`).
LAYER_FIELDS = (
    "status", "is_officeholder", "level", "department", "role", "role_title", "majlis", "region",
)
PUBLIC_FIELDS = LAYER_FIELDS  # what /me returns (no source, no flags)
AUDIT_ACTIONS = ("derive", "recompute", "override_set", "override_clear", "roster_apply", "preview_as")

_PRESERVE_FLAGS_DROP = {"needs_review", "ambiguous_slug", "unconfirmed_slug"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


# ---------------------------------------------------------------------------
# override / roster layers
# ---------------------------------------------------------------------------

def validate_layer(layer: Any, rules: IdentityRules) -> dict:
    """Validate a partial attribute dict (override or roster). Raises ValueError.

    Returns a cleaned copy containing only known keys; ``None`` values are kept
    (explicitly nulling a field is meaningful).
    """
    if not isinstance(layer, dict) or not layer:
        raise ValueError("Provide at least one attribute")
    unknown = set(layer) - set(LAYER_FIELDS)
    if unknown:
        raise ValueError(f"Unknown attribute(s): {', '.join(sorted(map(str, unknown)))}")
    out: dict[str, Any] = dict(layer)

    # Type-check BEFORE any membership test: unhashable values ({"majlis": []}) must be a
    # clean validation error, never a TypeError/500 (and never abort a roster import).
    for key in ("status", "level", "department", "role", "majlis", "region", "role_title"):
        if key in out and out[key] is not None and not isinstance(out[key], str):
            raise ValueError(f"{key} must be a string or null")
    if "is_officeholder" in out and out["is_officeholder"] is not None and not isinstance(out["is_officeholder"], bool):
        raise ValueError("is_officeholder must be true, false or null")
    if out.get("status") == "not_applicable" and (
        out.get("is_officeholder") is True or out.get("level") or out.get("role") or out.get("department")
    ):
        raise ValueError("A not_applicable status cannot carry an officeholder role")

    if "status" in out and out["status"] not in STATUSES:
        raise ValueError("Invalid status")
    if "level" in out and out["level"] is not None and out["level"] not in LEVELS:
        raise ValueError("Invalid level")
    if "department" in out and out["department"] is not None and out["department"] not in rules.department_names:
        raise ValueError("Unknown department")
    role_keys = {k.split(":")[0] for k in rules.role_titles}
    if "role" in out and out["role"] is not None and out["role"] not in role_keys:
        raise ValueError("Unknown role")
    if "majlis" in out and out["majlis"] is not None and out["majlis"] not in MAJLIS_TO_REGION:
        raise ValueError("Unknown Majlis")
    if "region" in out and out["region"] is not None and out["region"] not in set(MAJLIS_TO_REGION.values()):
        raise ValueError("Unknown region")
    if out.get("majlis") and out.get("region") and MAJLIS_TO_REGION[out["majlis"]] != out["region"]:
        raise ValueError("Region does not match the Majlis")
    if "is_officeholder" in out and out["is_officeholder"] is not None and not isinstance(out["is_officeholder"], bool):
        raise ValueError("is_officeholder must be true, false or null")
    if "role_title" in out and out["role_title"] is not None:
        if not isinstance(out["role_title"], str) or len(out["role_title"]) > 100:
            raise ValueError("role_title must be a string of at most 100 characters")
    return out


def compute_effective(
    derived: dict,
    roster: Optional[dict],
    override: Optional[dict],
    rules: IdentityRules,
) -> dict:
    """admin override > roster override > parser. Pure."""
    eff: dict[str, Any] = {k: derived.get(k) for k in LAYER_FIELDS}
    eff["source"] = derived.get("source", "parser")
    eff["flags"] = list(derived.get("flags", []))

    applied_source: Optional[str] = None
    explicit_status = False
    explicit_holder = False
    explicit_title = False
    sets_role_or_level = False
    for layer, name in ((roster, "roster"), (override, "admin")):
        if not layer:
            continue
        applied_source = name
        for k, v in layer.items():
            if k not in LAYER_FIELDS:
                continue
            eff[k] = v
            explicit_status |= k == "status"
            explicit_holder |= k == "is_officeholder"
            explicit_title |= k == "role_title"
            sets_role_or_level |= k in ("role", "level") and v is not None
        # Setting a Majlis without a region derives the region from the canonical map.
        if layer.get("majlis") and "region" not in layer:
            eff["region"] = MAJLIS_TO_REGION.get(layer["majlis"])
        if ("role" in layer or "department" in layer or "level" in layer) and "role_title" not in layer:
            eff["role_title"] = rules.title(eff.get("role"), eff.get("level"), eff.get("department"))

    if applied_source:
        eff["source"] = applied_source
        # SAFEST RULE: a layer promotes an account to a matched officeholder ONLY when it
        # sets a role or a level (i.e. says what the person holds). A partial layer such as
        # {"majlis": "Albany"} never changes status / is_officeholder implicitly.
        if not explicit_status and sets_role_or_level:
            eff["status"] = "matched"
        if not explicit_holder and sets_role_or_level:
            eff["is_officeholder"] = True
        eff["flags"] = [f for f in eff["flags"] if f not in _PRESERVE_FLAGS_DROP]
        eff["flags"].append(f"{applied_source}_override")
    return eff


def effective_public(effective: dict) -> dict:
    return {k: effective.get(k) for k in PUBLIC_FIELDS}


# Shape returned when a user has no attribute row yet: unknown, never "not an officeholder".
UNKNOWN_PUBLIC: dict = {
    "status": "unrecognized", "is_officeholder": None, "level": None, "department": None,
    "role": None, "role_title": None, "majlis": None, "region": None,
}


class CrossOrgConflict(Exception):
    """A write would change what a user appears as in another organization."""


async def assert_exclusive_to_org(db: AsyncSession, user_id: int, org_id: int) -> None:
    """The attribute store is deployment-global BY DESIGN (MKA is single-org): one row per
    user, whichever org's admin writes. This guard keeps multi-org installs safe: a write
    (override set/clear, roster apply matching a user) is allowed only if all of the
    target's org memberships are within {org_id}; otherwise it is refused (HTTP 409)."""
    # TOCTOU: lock the target `user` row first (FOR UPDATE; a no-op on SQLite) so the check
    # and the write share one locked section, and callers re-run this check immediately
    # before committing (``_recheck_then_commit``). Residual risk: an org-join racing the
    # final re-check. Acceptable: the store is deployment-global by design (MKA is single-org).
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())
    orgs = set(
        (await db.execute(select(UserOrganization.org_id).where(UserOrganization.user_id == user_id)))
        .scalars().all()
    )
    if orgs - {org_id}:
        raise CrossOrgConflict(
            "This user belongs to other organizations; identity attributes are shared across "
            "them, so they can only be changed by a platform administrator."
        )


async def _recheck_then_commit(db: AsyncSession, user_id: Optional[int], org_id: Optional[int]) -> None:
    """Final re-check inside the locked section, then commit. On conflict: roll back, refuse."""
    if user_id is not None and org_id is not None:
        try:
            await assert_exclusive_to_org(db, user_id, org_id)
        except CrossOrgConflict:
            await db.rollback()
            raise
    await db.commit()


def _version_tuple(v: Optional[str]) -> tuple:
    out = []
    for part in (v or "").split("."):
        out.append(int(part) if part.isdigit() else -1)
    return tuple(out)


STALE_PUBLIC: dict = {
    "status": "unrecognized", "is_officeholder": False, "level": None, "department": None,
    "role": None, "role_title": None, "majlis": None, "region": None,
}


def _domain(email: Optional[str]) -> str:
    e = normalize_email(email)
    return e.rsplit("@", 1)[1] if "@" in e else ""


def is_stale(row: MkaUserAttributes, user: User, rules: Optional[IdentityRules] = None) -> bool:
    """Fail-closed freshness check for a stored row (see ``read_effective``).

    An officeholder-capable row (derived status other than not_applicable) is only
    trusted when Workspace ownership of its email domain was PROVEN (``verified_hd``
    equals the domain of ``email_seen``) or an admin override exists."""
    rules = rules or get_rules()
    if row.stale:
        return True
    if row.email_seen != normalize_email(user.email):
        return True
    if (
        row.override is None
        and (row.derived or {}).get("status") != "not_applicable"
        and (row.verified_hd or "") != _domain(row.email_seen)
    ):
        return True
    if _version_tuple(row.rules_version) < _version_tuple(rules.version):
        return True
    return False


def is_address_proven(row: Optional[MkaUserAttributes], user: User, rules: Optional[IdentityRules] = None) -> bool:
    """True when Workspace ownership of the account's CURRENT address is proven by a fresh row: ``verified_hd`` equals the
    domain of ``email_seen``, ``email_seen`` is still the account's email, and the row is not marked stale. Mailbox
    ownership does not depend on the identity-rules version, so a rules bump does NOT invalidate it (it only marks the
    ATTRIBUTES for refresh, see ``is_stale``). An admin override does NOT count (it changes attributes, it does not prove
    who owns the mailbox). Used by compliance matching and by attribute-based compliance scope."""
    if row is None or not row.verified_hd or row.stale:
        return False
    return row.verified_hd == _domain(row.email_seen) and row.email_seen == normalize_email(user.email)


def read_effective_from_row(row: Optional[MkaUserAttributes], user: User) -> tuple[dict, bool]:
    """(public attributes, stale). Missing row -> unknown (unrecognized, null holder);
    stale row -> unrecognized, is_officeholder False. Never returns a cached elevated value
    that no longer matches the account."""
    if row is None:
        return dict(UNKNOWN_PUBLIC), False
    if is_stale(row, user):
        return dict(STALE_PUBLIC), True
    return effective_public(row.effective), False


async def read_effective(db: AsyncSession, user: User) -> tuple[dict, bool]:
    """THE server-side read for consumers (/me, admin list, audience counts...): fails closed."""
    return read_effective_from_row(await get_row(db, user.id), user)


# ---------------------------------------------------------------------------
# persistence helpers
# ---------------------------------------------------------------------------

def get_rules() -> IdentityRules:
    return load_rules()


async def get_row(db: AsyncSession, user_id: int) -> Optional[MkaUserAttributes]:
    return (
        await db.execute(select(MkaUserAttributes).where(MkaUserAttributes.user_id == user_id))
    ).scalars().first()


async def get_roster_row(db: AsyncSession, org_id: int, email: str) -> Optional[MkaRosterOverride]:
    """The roster row of ONE org for an email (admin routes are always org-scoped)."""
    return (
        await db.execute(
            select(MkaRosterOverride).where(
                MkaRosterOverride.org_id == org_id, MkaRosterOverride.email == normalize_email(email)
            )
        )
    ).scalars().first()


async def roster_for_user(db: AsyncSession, user_id: int, email: str) -> Optional[MkaRosterOverride]:
    """Roster row that applies to a user: only the row of the ONE org the user belongs to.

    A user in several orgs gets NO roster layer (None): a roster row written by one org
    must never decide what a shared account appears as (cross-tenant injection via a
    pre-seeded roster + later membership). Admin overrides (guarded by 409) remain."""
    orgs = (
        await db.execute(select(UserOrganization.org_id).where(UserOrganization.user_id == user_id))
    ).scalars().all()
    if len(set(orgs)) != 1:
        return None
    return await get_roster_row(db, orgs[0], email)


def _effective(derived: dict, roster_row: Optional[MkaRosterOverride], override: Optional[dict], rules: IdentityRules) -> dict:
    eff = compute_effective(derived, roster_row.attributes if roster_row else None, override, rules)
    if roster_row is not None:
        eff["roster_org_id"] = roster_row.org_id
    return eff


def _add_audit(
    db: AsyncSession,
    user_id: int,
    action: str,
    before: Optional[dict],
    after: Optional[dict],
    *,
    actor_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> None:
    assert action in AUDIT_ACTIONS
    db.add(
        MkaUserAttributesAudit(
            user_id=user_id, actor_user_id=actor_user_id, action=action,
            before=before, after=after, reason=reason, at=_now(),
        )
    )


def _snapshot(row: MkaUserAttributes) -> dict:
    return {"derived": row.derived, "effective": row.effective, "override": row.override}


def _apply_effective_columns(row: MkaUserAttributes, eff: dict) -> None:
    row.effective = eff
    row.eff_status = eff.get("status")
    row.eff_is_officeholder = eff.get("is_officeholder")
    row.eff_level = eff.get("level")
    row.eff_department = eff.get("department")
    row.eff_role = eff.get("role")
    row.eff_majlis = eff.get("majlis")
    row.eff_region = eff.get("region")


BLANK_DERIVED = {
    "status": "unrecognized", "is_officeholder": None, "level": None, "department": None,
    "role": None, "role_title": None, "majlis": None, "region": None, "source": "parser",
    "flags": ["unverified_domain"],
}


async def refresh_attributes(
    db: AsyncSession,
    user: User,
    *,
    action: str = "derive",
    actor_user_id: Optional[int] = None,
    rules: Optional[IdentityRules] = None,
    proof_hd: Optional[str] = None,
) -> tuple[Optional[MkaUserAttributes], bool]:
    """Derive + store attributes for ``user``. Idempotent. Does NOT commit.

    TRUST BOUNDARY. Officeholder attributes are derived from an email only when
    Workspace ownership of its domain is proven, by ANY of:
      * ``proof_hd`` == the email domain (the verified ``hd`` claim of THIS Google login),
      * the row already records that proof (``verified_hd`` from an earlier login),
      * the account signed up with Google AND its domain is in MKA_GOOGLE_ONLY_DOMAINS
        (upstream then enforced ``hd`` at every Google login).
    Without proof the derived value is BLANK (unrecognized), never a parse of the address.
    An account that is not a Google signup and has no proof gets no row at all.

    Returns ``(row, changed)``; ``row`` may be None when skipped. An audit row is written
    only when the derived value changed (or the row is new, or the roster layer changed
    the effective result); an unchanged recompute writes nothing.
    """
    rules = rules or get_rules()
    email = normalize_email(user.email)
    domain = _domain(email)
    row = await get_row(db, user.id)
    proven = bool(domain) and (
        (proof_hd or "").strip().lower() == domain
        or (row is not None and (row.verified_hd or "") == domain and row.email_seen == email)  # proof is per ADDRESS
        or (user.signup_method == "google" and is_google_only_email(email))
    )
    if not proven and user.signup_method != "google" and (proof_hd is None):
        return row, False
    parsed = parse_identity(email, rules).to_dict()
    derived = parsed if (proven or parsed["status"] == "not_applicable") else dict(BLANK_DERIVED)
    verified_hd = domain if proven else None
    roster_row = await roster_for_user(db, user.id, email)

    if row is None:
        eff = _effective(derived, roster_row, None, rules)
        row = MkaUserAttributes(
            user_id=user.id, email_seen=email, derived=derived, rules_version=rules.version,
            derived_at=_now(), verified_hd=verified_hd,
        )
        row.stale = False
        _apply_effective_columns(row, eff)
        db.add(row)
        _add_audit(db, user.id, action, None, _snapshot(row), actor_user_id=actor_user_id)
        return row, True

    eff = _effective(derived, roster_row, row.override, rules)
    derived_changed = row.derived != derived
    eff_changed = row.effective != eff
    version_changed = row.rules_version != rules.version
    email_changed = row.email_seen != email
    proof_changed = row.verified_hd != verified_hd
    if row.stale:
        row.stale = False
        db.add(row)
    if not (derived_changed or eff_changed or version_changed or email_changed or proof_changed):
        return row, False

    before = _snapshot(row)
    if derived_changed:
        row.derived = derived
        row.derived_at = _now()
    row.rules_version = rules.version
    row.email_seen = email
    row.verified_hd = verified_hd
    if eff_changed:
        _apply_effective_columns(row, eff)
    db.add(row)
    if derived_changed:
        _add_audit(db, user.id, action, before, _snapshot(row), actor_user_id=actor_user_id)
    elif eff_changed:
        _add_audit(db, user.id, "roster_apply", before, _snapshot(row), actor_user_id=actor_user_id)
    return row, derived_changed or eff_changed or proof_changed


def _new_session(db_session: AsyncSession) -> AsyncSession:
    """A SEPARATE session on the same engine: the hook never commits, rolls back or reloads
    the caller's session, so no failure here can touch the login path."""
    return AsyncSession(bind=db_session.bind, expire_on_commit=False)


async def mka_refresh_on_login(db_session: AsyncSession, user: User, amr: Optional[str]) -> None:
    """Login hook (spec A2/A5). Google sign-ins only; FULLY FAIL-OPEN: never raises, and never
    touches the caller's session (own session; ``user`` is read through a plain snapshot taken
    before any I/O). On failure the existing row is marked stale (reads fail closed).
    The Workspace ``hd`` proof of this very login is read from the request-scoped record set
    by ``require_workspace_hd`` in the Google path."""
    if amr != AUTH_METHOD_GOOGLE:
        return
    try:
        snap = SimpleNamespace(id=user.id, email=user.email, signup_method=user.signup_method)
        proof = take_verified_hd(snap.email)
    except Exception:  # noqa: BLE001
        logger.exception("MKA hook: could not read the user (ignored)")
        return
    refreshed = False
    try:
        async with _new_session(db_session) as s:
            try:
                await refresh_attributes(s, snap, action="derive", proof_hd=proof)  # type: ignore[arg-type]
                await s.commit()
                refreshed = True
            except IntegrityError:
                await s.rollback()
                logger.info("MKA attribute refresh lost an insert race on login (ignored)")
            except Exception:  # noqa: BLE001 - fail-open for LOGIN by design
                logger.exception("MKA attribute refresh failed on login (ignored)")
                await s.rollback()
                await s.execute(
                    update(MkaUserAttributes).where(MkaUserAttributes.user_id == snap.id).values(stale=True)  # type: ignore[arg-type]
                )
                await s.commit()  # best effort: reads fail closed until a refresh succeeds
    except Exception:  # noqa: BLE001
        logger.exception("MKA attribute stale-mark failed (ignored)")
    if refreshed:
        await _autoenroll_after_refresh(db_session, snap)
    # ALWAYS, even when the refresh failed: an identity that cannot be trusted must still lose a managed role it holds
    # (fail closed). The sync itself re-checks proof and freshness and never grants on an untrusted row.
    await _identity_sync_after_refresh(db_session, snap)


async def _autoenroll_after_refresh(db_session: AsyncSession, snap: Any) -> None:
    """Auto-enrol (spec 2026-10-05 A): flag-gated, own session, never raises. Runs only after a SUCCESSFUL
    refresh so the proof it relies on (``is_address_proven``) is the row just written."""
    try:
        from src.services.mka import automation_config as _acfg

        if not _acfg.autoenroll_enabled():
            return
        from src.services.mka.automation_enroll import autoenroll_user

        await autoenroll_user(lambda: _new_session(db_session), snap)
    except Exception:  # noqa: BLE001
        logger.exception("MKA auto-enrol hook failed (ignored)")


async def _identity_sync_after_refresh(db_session: AsyncSession, snap: Any) -> None:
    """Identity sync (spec 2026-10-07 A3): Mohtamim role + managed groups. Flag-gated, own session, never raises. Runs only
    after a SUCCESSFUL refresh so the proof it relies on (``is_address_proven``) is the row just written."""
    try:
        from src.services.mka import identity_sync as _isync

        if not _isync.enabled():
            return
        await _isync.identity_sync_user(lambda: _new_session(db_session), snap)
    except Exception:  # noqa: BLE001
        logger.exception("MKA identity sync hook failed (ignored)")


async def recompute_users(
    db: AsyncSession,
    *,
    org_id: Optional[int] = None,
    actor_user_id: Optional[int] = None,
    dry_run: bool = False,
    batch_size: int = 500,
) -> dict:
    """Recompute attributes for existing users (backfill / rules bump).

    Processes Google signups and any user that already has a row (e.g. an invited account
    that later signed in with Google). Derivation is proof-gated inside ``refresh_attributes``
    (a recompute can never CREATE proof, only reuse what a Google login recorded), so there
    is deliberately no "include unverified accounts" switch.
    Commits per batch (unless ``dry_run``, which rolls back at the end).
    """
    rules = get_rules()
    counts = {"processed": 0, "created": 0, "changed": 0, "unchanged": 0, "rules_version": rules.version}
    last_id = 0
    while True:
        stmt = select(User).where(User.id > last_id).order_by(User.id).limit(batch_size)  # type: ignore[arg-type]
        if org_id is not None:
            stmt = stmt.where(
                User.id.in_(  # type: ignore[attr-defined]
                    select(UserOrganization.user_id).where(UserOrganization.org_id == org_id)
                )
            )
        stmt = stmt.where(
            or_(
                User.signup_method == "google",
                User.id.in_(select(MkaUserAttributes.user_id)),  # type: ignore[attr-defined]
            )
        )
        users = (await db.execute(stmt)).scalars().all()
        if not users:
            break
        for u in users:
            last_id = u.id
            existed = await get_row(db, u.id) is not None
            _, changed = await refresh_attributes(
                db, u, action="recompute", actor_user_id=actor_user_id, rules=rules,
            )
            counts["processed"] += 1
            if not existed:
                counts["created"] += 1
            elif changed:
                counts["changed"] += 1
            else:
                counts["unchanged"] += 1
        if not dry_run:
            await db.commit()
        else:
            await db.flush()
    if dry_run:
        await db.rollback()
    return counts


# ---------------------------------------------------------------------------
# admin: overrides
# ---------------------------------------------------------------------------

async def set_override(
    db: AsyncSession, user: User, override: dict, reason: str, actor_user_id: int,
    org_id: Optional[int] = None,
) -> MkaUserAttributes:
    rules = get_rules()
    layer = validate_layer(override, rules)
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A reason is required")
    if org_id is not None:
        await assert_exclusive_to_org(db, user.id, org_id)
    row, _ = await refresh_attributes(db, user, action="derive", actor_user_id=actor_user_id, rules=rules)
    if row is None:
        # Unverified (non-Google) account: the one deliberate exception. The row is
        # created with a BLANK derived value (never parsed from the unverified email);
        # only the admin override gives it attributes.
        blank = dict(BLANK_DERIVED)
        row = MkaUserAttributes(
            user_id=user.id, email_seen=normalize_email(user.email), derived=blank,
            rules_version=rules.version, derived_at=_now(),
        )
        _apply_effective_columns(row, compute_effective(blank, None, None, rules))
        db.add(row)
        await db.flush()
    before = _snapshot(row)
    roster_row = await roster_for_user(db, user.id, row.email_seen)
    row.override = layer
    row.override_reason = reason
    row.override_by = actor_user_id
    row.override_at = _now()
    _apply_effective_columns(
        row, _effective(row.derived, roster_row, layer, rules)
    )
    db.add(row)
    _add_audit(db, user.id, "override_set", before, _snapshot(row), actor_user_id=actor_user_id, reason=reason)
    await _recheck_then_commit(db, user.id, org_id)
    return row


async def clear_override(
    db: AsyncSession, user: User, actor_user_id: int, reason: Optional[str] = None,
    org_id: Optional[int] = None,
) -> Optional[MkaUserAttributes]:
    if org_id is not None:
        await assert_exclusive_to_org(db, user.id, org_id)
    row = await get_row(db, user.id)
    if row is None or row.override is None:
        return row
    rules = get_rules()
    before = _snapshot(row)
    roster_row = await roster_for_user(db, user.id, row.email_seen)
    row.override = None
    row.override_reason = None
    row.override_by = None
    row.override_at = None
    _apply_effective_columns(
        row, _effective(row.derived, roster_row, None, rules)
    )
    db.add(row)
    _add_audit(db, user.id, "override_clear", before, _snapshot(row), actor_user_id=actor_user_id, reason=reason)
    await _recheck_then_commit(db, user.id, org_id)
    return row


# ---------------------------------------------------------------------------
# admin: roster overrides (per email, may precede the user)
# ---------------------------------------------------------------------------

async def _guard_roster_target(db: AsyncSession, org_id: int, email: str) -> None:
    user = (
        await db.execute(
            select(User)
            .join(UserOrganization, UserOrganization.user_id == User.id)  # type: ignore[arg-type]
            .where(func.lower(User.email) == email, UserOrganization.org_id == org_id)
        )
    ).scalars().first()
    if user is not None:
        await assert_exclusive_to_org(db, user.id, org_id)


async def _recheck_roster_then_commit(db: AsyncSession, org_id: int, emails: list[str]) -> None:
    try:
        for e in emails:
            await _guard_roster_target(db, org_id, e)
    except CrossOrgConflict:
        await db.rollback()
        raise
    await db.commit()


async def _reapply_roster_to_user(
    db: AsyncSession, org_id: int, email: str, actor_user_id: Optional[int], rules: IdentityRules
) -> None:
    """After a roster change in ``org_id``, refresh the matching user's effective values,
    but ONLY a user who is a member of that org (a roster row never reaches other orgs)."""
    user = (
        await db.execute(
            select(User)
            .join(UserOrganization, UserOrganization.user_id == User.id)  # type: ignore[arg-type]
            .where(func.lower(User.email) == email, UserOrganization.org_id == org_id)
        )
    ).scalars().first()
    if user is None:
        return
    if await get_row(db, user.id) is None:
        return  # not derived yet: the first Google login will pick the roster up
    await refresh_attributes(db, user, action="recompute", actor_user_id=actor_user_id, rules=rules)


async def upsert_roster(
    db: AsyncSession,
    org_id: int,
    email: str,
    attributes: dict,
    *,
    source: str,
    note: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    commit: bool = True,
) -> MkaRosterOverride:
    rules = get_rules()
    email = normalize_email(email)
    if not email or "@" not in email or any(c.isspace() for c in email):
        raise ValueError("Invalid email")
    layer = validate_layer(attributes, rules)
    await _guard_roster_target(db, org_id, email)
    row = await get_roster_row(db, org_id, email)
    if row is None:
        row = MkaRosterOverride(org_id=org_id, email=email, attributes=layer, source=source, note=note,
                                updated_at=_now(), updated_by=actor_user_id)
    else:
        row.attributes = layer
        row.source = source
        row.note = note
        row.updated_at = _now()
        row.updated_by = actor_user_id
    db.add(row)
    await db.flush()
    await _reapply_roster_to_user(db, org_id, email, actor_user_id, rules)
    if commit:
        await _recheck_roster_then_commit(db, org_id, [email])
    return row


async def delete_roster(
    db: AsyncSession, org_id: int, email: str, actor_user_id: Optional[int] = None, commit: bool = True
) -> bool:
    rules = get_rules()
    email = normalize_email(email)
    row = await get_roster_row(db, org_id, email)
    if row is None:
        return False
    await _guard_roster_target(db, org_id, email)
    await db.delete(row)
    await db.flush()
    await _reapply_roster_to_user(db, org_id, email, actor_user_id, rules)
    if commit:
        await _recheck_roster_then_commit(db, org_id, [email])
    return True


async def import_roster(
    db: AsyncSession,
    org_id: int,
    rows: Iterable[dict],
    *,
    source: str,
    actor_user_id: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    """Apply many roster rows. One bad row never aborts the batch; each gets a result."""
    results = []
    ok = 0
    applied_emails: list[str] = []
    for i, r in enumerate(rows):
        try:
            await upsert_roster(
                db, org_id, r.get("email", ""), r.get("attributes") or {}, source=source,
                note=r.get("note"), actor_user_id=actor_user_id, commit=False,
            )
            results.append({"index": i, "email": normalize_email(r.get("email")), "ok": True})
            applied_emails.append(normalize_email(r.get("email")))
            ok += 1
        except (ValueError, TypeError, CrossOrgConflict) as exc:
            results.append({"index": i, "email": normalize_email(r.get("email")), "ok": False, "error": str(exc)})
    if dry_run:
        await db.rollback()
    else:
        await _recheck_roster_then_commit(db, org_id, applied_emails)  # CrossOrgConflict -> whole batch refused
    return {"applied": 0 if dry_run else ok, "valid": ok, "failed": len(results) - ok,
            "dry_run": dry_run, "results": results}


# ---------------------------------------------------------------------------
# admin: listing
# ---------------------------------------------------------------------------

LIST_FILTERS = {
    "status": MkaUserAttributes.eff_status,
    "level": MkaUserAttributes.eff_level,
    "department": MkaUserAttributes.eff_department,
    "region": MkaUserAttributes.eff_region,
    "majlis": MkaUserAttributes.eff_majlis,
}
MAX_PAGE_SIZE = 200


def _admin_view(user: User, row: MkaUserAttributes, redact: bool = False, token_view: bool = False) -> dict:
    """``redact`` hides override content/reasons/actors: used for API tokens and for users
    shared with other orgs (another org's admin notes are not this org's business)."""
    _read = read_effective_from_row(row, user)
    if token_view:
        # API tokens (companion service) get ONLY the fail-closed effective value: no raw cache,
        # derived value or override metadata.
        return {
            "user_id": user.id, "user_uuid": user.user_uuid, "email": user.email,
            "effective": _read[0], "stale": _read[1], "rules_version": row.rules_version,
        }
    return {
        "user_id": user.id,
        "user_uuid": user.user_uuid,
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        # FAIL CLOSED: consumers scope access from `effective`; a stale/drifted row reads as
        # unrecognized. The raw cached value stays visible for admins as `stored_effective`.
        "effective": _read[0],
        "stale": _read[1],
        "stored_effective": row.effective,
        "derived": row.derived,
        "override": None if redact else row.override,
        "override_reason": None if redact else row.override_reason,
        "override_by": None if redact else row.override_by,
        "override_at": None if redact or not row.override_at else row.override_at.isoformat(),
        "redacted": redact,
        "rules_version": row.rules_version,
        "derived_at": row.derived_at.isoformat() if row.derived_at else None,
    }


async def list_attributes(
    db: AsyncSession,
    org_id: int,
    *,
    filters: Optional[dict] = None,
    q: Optional[str] = None,
    has_override: Optional[bool] = None,
    mismatch: Optional[bool] = None,
    page: int = 1,
    page_size: int = 50,
    redact: bool = False,
    token_view: bool = False,
) -> dict:
    """Org-scoped, filtered, paginated list (effective + derived + override).

    The ``eff_*`` columns are a cache that ignores freshness, so every attribute filter
    also applies the fail-closed rule in SQL: a stale row (flag, email drift, other rules
    version, or an officeholder-capable row without proven domain ownership and without an
    override) never matches level/department/region/majlis, and matches ``status`` only as
    "unrecognized" (which is what it reads as)."""
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    conds = [UserOrganization.org_id == org_id]
    stale_sql = or_(
        MkaUserAttributes.stale.is_(True),
        MkaUserAttributes.email_seen != func.lower(User.email),
        MkaUserAttributes.rules_version != get_rules().version,
        and_(
            MkaUserAttributes.override.is_(None),
            MkaUserAttributes.verified_hd.is_(None),
            MkaUserAttributes.eff_status != "not_applicable",
        ),
    )
    fresh_sql = ~stale_sql
    for key, value in (filters or {}).items():
        if value is None or key not in LIST_FILTERS:
            continue
        values = list(value) if isinstance(value, (list, tuple, set)) else [value]
        if key == "status":
            conds.append(
                or_(
                    and_(fresh_sql, LIST_FILTERS[key].in_(values)),  # type: ignore[attr-defined]
                    and_(stale_sql, "unrecognized" in values),
                )
            )
        else:
            conds.append(fresh_sql)
            conds.append(LIST_FILTERS[key].in_(values))  # type: ignore[attr-defined]
    if mismatch is True:
        # Self-reported Majlis (mka_user_profile) disagrees with the derived/effective one.
        from src.db.mka_user_profile import MkaUserProfile

        conds.append(MkaUserAttributes.eff_majlis.is_not(None))  # type: ignore[union-attr]
        conds.append(fresh_sql)
        conds.append(
            MkaUserAttributes.user_id.in_(  # type: ignore[attr-defined]
                select(MkaUserProfile.user_id).where(MkaUserProfile.majlis != MkaUserAttributes.eff_majlis)
            )
        )
    if has_override is True:
        conds.append(MkaUserAttributes.override.is_not(None))  # type: ignore[union-attr]
    elif has_override is False:
        conds.append(MkaUserAttributes.override.is_(None))  # type: ignore[union-attr]
    if q:
        needle = f"%{q.strip().lower().replace('%', '').replace('_', '')}%"
        conds.append(func.lower(MkaUserAttributes.email_seen).like(needle))

    base = (
        select(User, MkaUserAttributes)
        .join(MkaUserAttributes, MkaUserAttributes.user_id == User.id)  # type: ignore[arg-type]
        .join(UserOrganization, UserOrganization.user_id == User.id)  # type: ignore[arg-type]
        .where(*conds)
    )
    total = (
        await db.execute(
            select(func.count())
            .select_from(MkaUserAttributes)
            .join(User, User.id == MkaUserAttributes.user_id)  # type: ignore[arg-type]
            .join(UserOrganization, UserOrganization.user_id == MkaUserAttributes.user_id)
            .where(*conds)
        )
    ).scalar_one()
    rows = (
        await db.execute(base.order_by(User.id).offset((page - 1) * page_size).limit(page_size))  # type: ignore[arg-type]
    ).all()
    ids = [u.id for u, _ in rows]
    shared = set()
    if ids:
        shared = set(
            (await db.execute(
                select(UserOrganization.user_id).where(
                    UserOrganization.user_id.in_(ids), UserOrganization.org_id != org_id  # type: ignore[attr-defined]
                )
            )).scalars().all()
        )
    return {
        "items": [_admin_view(u, a, redact or u.id in shared, token_view) for u, a in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "rules_version": get_rules().version,
    }


async def is_shared_with_other_orgs(db: AsyncSession, user_id: int, org_id: int) -> bool:
    return (
        await db.execute(
            select(UserOrganization.org_id).where(
                UserOrganization.user_id == user_id, UserOrganization.org_id != org_id
            ).limit(1)
        )
    ).first() is not None


async def get_admin_view(db: AsyncSession, user: User, org_id: Optional[int] = None, redact: bool = False) -> Optional[dict]:
    row = await get_row(db, user.id)
    if row is None:
        return None
    if org_id is not None and not redact:
        redact = await is_shared_with_other_orgs(db, user.id, org_id)
    return _admin_view(user, row, redact)


async def list_audit(db: AsyncSession, user_id: int, limit: int = 100) -> list[dict]:
    rows = (
        await db.execute(
            select(MkaUserAttributesAudit)
            .where(MkaUserAttributesAudit.user_id == user_id)
            .order_by(MkaUserAttributesAudit.id.desc())  # type: ignore[union-attr]
            .limit(max(1, min(limit, 500)))
        )
    ).scalars().all()
    return [
        {
            "id": a.id, "action": a.action, "actor_user_id": a.actor_user_id,
            "reason": a.reason, "before": a.before, "after": a.after,
            "at": a.at.isoformat() if a.at else None,
        }
        for a in rows
    ]


def _subject_audit(items: list[dict]) -> list[dict]:
    """GDPR export: the subject's own history without other people's identifiers."""
    return [
        {"action": a["action"], "reason": a["reason"], "at": a["at"],
         "by": "system" if a["actor_user_id"] is None else "administrator"}
        for a in items
    ]


# ---------------------------------------------------------------------------
# GDPR (called from the fork's mka_profile.delete_profile / profile_status)
# ---------------------------------------------------------------------------

async def export_attributes(db: AsyncSession, user_id: int) -> Optional[dict]:
    """The user's own stored attributes for the GDPR export (None if no row)."""
    row = await get_row(db, user_id)
    if row is None:
        return None
    return {
        "email_seen": row.email_seen,
        "effective": effective_public(row.effective),
        "derived": effective_public(row.derived),
        "override": row.override,
        "rules_version": row.rules_version,
        "audit": _subject_audit(await list_audit(db, user_id)),
    }


async def delete_attributes(db: AsyncSession, user_id: int) -> None:
    """GDPR anonymize: remove the row, the user's audit history, the roster row for
    the email seen, and anonymise the user as actor elsewhere. Does NOT commit.
    (Hard-deleting a user needs no call: the FKs cascade / set NULL.)"""
    row = await get_row(db, user_id)
    if row is not None:
        # Only roster rows of orgs the departing user belongs to; other orgs' rows for
        # the same email are not ours to delete.
        member_orgs = select(UserOrganization.org_id).where(UserOrganization.user_id == user_id)
        await db.execute(
            delete(MkaRosterOverride).where(
                MkaRosterOverride.email == row.email_seen,
                MkaRosterOverride.org_id.in_(member_orgs),  # type: ignore[attr-defined]
            )
        )
    await db.execute(delete(MkaUserAttributesAudit).where(MkaUserAttributesAudit.user_id == user_id))  # type: ignore[arg-type]
    await db.execute(
        update(MkaUserAttributesAudit)
        .where(MkaUserAttributesAudit.actor_user_id == user_id)  # type: ignore[arg-type]
        .values(actor_user_id=None)
    )
    await db.execute(
        update(MkaUserAttributes)
        .where(MkaUserAttributes.override_by == user_id)  # type: ignore[arg-type]
        .values(override_by=None)
    )
    await db.execute(
        update(MkaRosterOverride)
        .where(MkaRosterOverride.updated_by == user_id)  # type: ignore[arg-type]
        .values(updated_by=None)
    )
    await db.execute(delete(MkaUserAttributes).where(MkaUserAttributes.user_id == user_id))  # type: ignore[arg-type]
