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
from typing import Any, Iterable, Optional

from sqlalchemy import delete, func, update
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
from src.services.users.mka_profile import MAJLIS_TO_REGION

logger = logging.getLogger(__name__)

# Attribute fields an override / roster layer may set (never `source` or `flags`).
LAYER_FIELDS = (
    "status", "is_officeholder", "level", "department", "role", "role_title", "majlis", "region",
)
PUBLIC_FIELDS = LAYER_FIELDS  # what /me returns (no source, no flags)
AUDIT_ACTIONS = ("derive", "recompute", "override_set", "override_clear", "roster_apply")

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
        # Setting a Majlis without a region derives the region from the canonical map.
        if layer.get("majlis") and "region" not in layer:
            eff["region"] = MAJLIS_TO_REGION.get(layer["majlis"])
        if ("role" in layer or "department" in layer or "level" in layer) and "role_title" not in layer:
            eff["role_title"] = rules.title(eff.get("role"), eff.get("level"), eff.get("department"))

    if applied_source:
        eff["source"] = applied_source
        if not explicit_status:
            eff["status"] = "matched"
        if not explicit_holder:
            eff["is_officeholder"] = True if eff["status"] in ("matched", "partial") else eff["is_officeholder"]
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


# ---------------------------------------------------------------------------
# persistence helpers
# ---------------------------------------------------------------------------

def get_rules() -> IdentityRules:
    return load_rules()


async def get_row(db: AsyncSession, user_id: int) -> Optional[MkaUserAttributes]:
    return (
        await db.execute(select(MkaUserAttributes).where(MkaUserAttributes.user_id == user_id))
    ).scalars().first()


async def get_roster_row(db: AsyncSession, email: str) -> Optional[MkaRosterOverride]:
    return (
        await db.execute(select(MkaRosterOverride).where(MkaRosterOverride.email == normalize_email(email)))
    ).scalars().first()


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


async def refresh_attributes(
    db: AsyncSession,
    user: User,
    *,
    action: str = "derive",
    actor_user_id: Optional[int] = None,
    rules: Optional[IdentityRules] = None,
    allow_unverified: bool = False,
) -> tuple[Optional[MkaUserAttributes], bool]:
    """Derive + store attributes for ``user``. Idempotent. Does NOT commit.

    Returns ``(row, changed)`` (``row`` may be None when skipped for an unverified
    account). An audit row is written only when the derived
    value changed (or the row is new, or the roster layer changed the effective
    result); an unchanged recompute writes nothing.
    """
    # Trust boundary: derive only for accounts whose email Google verified
    # (signup_method == 'google'). Anything else keeps whatever it has (usually
    # nothing) unless an operator explicitly opts in (backfill --include-non-google).
    if not allow_unverified and user.signup_method != "google":
        return await get_row(db, user.id), False
    rules = rules or get_rules()
    email = normalize_email(user.email)
    derived = parse_identity(email, rules).to_dict()
    roster_row = await get_roster_row(db, email)
    roster = roster_row.attributes if roster_row else None

    row = await get_row(db, user.id)
    if row is None:
        eff = compute_effective(derived, roster, None, rules)
        row = MkaUserAttributes(
            user_id=user.id, email_seen=email, derived=derived, rules_version=rules.version,
            derived_at=_now(),
        )
        _apply_effective_columns(row, eff)
        db.add(row)
        _add_audit(db, user.id, action, None, _snapshot(row), actor_user_id=actor_user_id)
        return row, True

    eff = compute_effective(derived, roster, row.override, rules)
    derived_changed = row.derived != derived
    eff_changed = row.effective != eff
    version_changed = row.rules_version != rules.version
    email_changed = row.email_seen != email
    if not (derived_changed or eff_changed or version_changed or email_changed):
        return row, False

    before = _snapshot(row)
    if derived_changed:
        row.derived = derived
        row.derived_at = _now()
    row.rules_version = rules.version
    row.email_seen = email
    if eff_changed:
        _apply_effective_columns(row, eff)
    db.add(row)
    if derived_changed:
        _add_audit(db, user.id, action, before, _snapshot(row), actor_user_id=actor_user_id)
    elif eff_changed:
        _add_audit(db, user.id, "roster_apply", before, _snapshot(row), actor_user_id=actor_user_id)
    return row, derived_changed or eff_changed


async def mka_refresh_on_login(db_session: AsyncSession, user: User, amr: Optional[str]) -> None:
    """Login hook (spec A2/A5). Google sign-ins only; FAIL-OPEN: nothing here may
    ever block or break a login, so every error is logged and swallowed. The work
    runs in a SAVEPOINT so a failure cannot poison the caller's transaction."""
    if amr != AUTH_METHOD_GOOGLE:
        return
    try:
        # SAVEPOINT: a failure rolls back only our work. We deliberately do NOT call
        # session.rollback() on this path: that would expire the caller's `user`
        # object and break the session minting that follows (MissingGreenlet).
        async with db_session.begin_nested():
            await refresh_attributes(db_session, user, action="derive")
    except Exception:  # noqa: BLE001 - fail-open by design
        logger.exception("MKA attribute refresh failed on login (ignored)")
        return
    try:
        await db_session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("MKA attribute commit failed on login (ignored)")
        try:
            await db_session.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("MKA attribute refresh: rollback failed (ignored)")


async def recompute_users(
    db: AsyncSession,
    *,
    org_id: Optional[int] = None,
    google_only: bool = True,
    actor_user_id: Optional[int] = None,
    dry_run: bool = False,
    batch_size: int = 500,
) -> dict:
    """Recompute attributes for existing users (backfill / rules bump).

    ``google_only`` restricts to ``signup_method == 'google'``: an account made by
    password signup must not pick up officeholder attributes from its address.
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
        if google_only:
            stmt = stmt.where(User.signup_method == "google")
        users = (await db.execute(stmt)).scalars().all()
        if not users:
            break
        for u in users:
            last_id = u.id
            existed = await get_row(db, u.id) is not None
            _, changed = await refresh_attributes(
                db, u, action="recompute", actor_user_id=actor_user_id, rules=rules,
                allow_unverified=not google_only,
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
    db: AsyncSession, user: User, override: dict, reason: str, actor_user_id: int
) -> MkaUserAttributes:
    rules = get_rules()
    layer = validate_layer(override, rules)
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A reason is required")
    row, _ = await refresh_attributes(db, user, action="derive", actor_user_id=actor_user_id, rules=rules)
    if row is None:
        # Unverified (non-Google) account: the one deliberate exception. The row is
        # created with a BLANK derived value (never parsed from the unverified email);
        # only the admin override gives it attributes.
        blank = parse_identity("", rules).to_dict()
        row = MkaUserAttributes(
            user_id=user.id, email_seen=normalize_email(user.email), derived=blank,
            rules_version=rules.version, derived_at=_now(),
        )
        _apply_effective_columns(row, compute_effective(blank, None, None, rules))
        db.add(row)
        await db.flush()
    before = _snapshot(row)
    roster_row = await get_roster_row(db, row.email_seen)
    row.override = layer
    row.override_reason = reason
    row.override_by = actor_user_id
    row.override_at = _now()
    _apply_effective_columns(
        row, compute_effective(row.derived, roster_row.attributes if roster_row else None, layer, rules)
    )
    db.add(row)
    _add_audit(db, user.id, "override_set", before, _snapshot(row), actor_user_id=actor_user_id, reason=reason)
    await db.commit()
    return row


async def clear_override(
    db: AsyncSession, user: User, actor_user_id: int, reason: Optional[str] = None
) -> Optional[MkaUserAttributes]:
    row = await get_row(db, user.id)
    if row is None or row.override is None:
        return row
    rules = get_rules()
    before = _snapshot(row)
    roster_row = await get_roster_row(db, row.email_seen)
    row.override = None
    row.override_reason = None
    row.override_by = None
    row.override_at = None
    _apply_effective_columns(
        row, compute_effective(row.derived, roster_row.attributes if roster_row else None, None, rules)
    )
    db.add(row)
    _add_audit(db, user.id, "override_clear", before, _snapshot(row), actor_user_id=actor_user_id, reason=reason)
    await db.commit()
    return row


# ---------------------------------------------------------------------------
# admin: roster overrides (per email, may precede the user)
# ---------------------------------------------------------------------------

async def _reapply_roster_to_user(
    db: AsyncSession, email: str, actor_user_id: Optional[int], rules: IdentityRules
) -> None:
    """After a roster change, refresh the matching user's effective values (if any)."""
    user = (
        await db.execute(select(User).where(func.lower(User.email) == email))
    ).scalars().first()
    if user is None:
        return
    if await get_row(db, user.id) is None:
        return  # not derived yet: the first Google login will pick the roster up
    await refresh_attributes(db, user, action="recompute", actor_user_id=actor_user_id, rules=rules)


async def upsert_roster(
    db: AsyncSession,
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
    row = await get_roster_row(db, email)
    if row is None:
        row = MkaRosterOverride(email=email, attributes=layer, source=source, note=note,
                                updated_at=_now(), updated_by=actor_user_id)
    else:
        row.attributes = layer
        row.source = source
        row.note = note
        row.updated_at = _now()
        row.updated_by = actor_user_id
    db.add(row)
    await db.flush()
    await _reapply_roster_to_user(db, email, actor_user_id, rules)
    if commit:
        await db.commit()
    return row


async def delete_roster(
    db: AsyncSession, email: str, actor_user_id: Optional[int] = None, commit: bool = True
) -> bool:
    rules = get_rules()
    email = normalize_email(email)
    row = await get_roster_row(db, email)
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    await _reapply_roster_to_user(db, email, actor_user_id, rules)
    if commit:
        await db.commit()
    return True


async def import_roster(
    db: AsyncSession,
    rows: Iterable[dict],
    *,
    source: str,
    actor_user_id: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    """Apply many roster rows. One bad row never aborts the batch; each gets a result."""
    results = []
    ok = 0
    for i, r in enumerate(rows):
        try:
            await upsert_roster(
                db, r.get("email", ""), r.get("attributes") or {}, source=source,
                note=r.get("note"), actor_user_id=actor_user_id, commit=False,
            )
            results.append({"index": i, "email": normalize_email(r.get("email")), "ok": True})
            ok += 1
        except ValueError as exc:
            results.append({"index": i, "email": normalize_email(r.get("email")), "ok": False, "error": str(exc)})
    if dry_run:
        await db.rollback()
    else:
        await db.commit()
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


def _admin_view(user: User, row: MkaUserAttributes) -> dict:
    return {
        "user_id": user.id,
        "user_uuid": user.user_uuid,
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "effective": row.effective,
        "derived": row.derived,
        "override": row.override,
        "override_reason": row.override_reason,
        "override_by": row.override_by,
        "override_at": row.override_at.isoformat() if row.override_at else None,
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
) -> dict:
    """Org-scoped, filtered, paginated list (effective + derived + override)."""
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    conds = [UserOrganization.org_id == org_id]
    for key, value in (filters or {}).items():
        if value is None or key not in LIST_FILTERS:
            continue
        if isinstance(value, (list, tuple, set)):  # e.g. status in (unrecognized, ambiguous, partial)
            conds.append(LIST_FILTERS[key].in_(list(value)))  # type: ignore[attr-defined]
        else:
            conds.append(LIST_FILTERS[key] == value)
    if mismatch is True:
        # Self-reported Majlis (mka_user_profile) disagrees with the derived/effective one.
        from src.db.mka_user_profile import MkaUserProfile

        conds.append(MkaUserAttributes.eff_majlis.is_not(None))  # type: ignore[union-attr]
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
            .join(UserOrganization, UserOrganization.user_id == MkaUserAttributes.user_id)
            .where(*conds)
        )
    ).scalar_one()
    rows = (
        await db.execute(base.order_by(User.id).offset((page - 1) * page_size).limit(page_size))  # type: ignore[arg-type]
    ).all()
    return {
        "items": [_admin_view(u, a) for u, a in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "rules_version": get_rules().version,
    }


async def get_admin_view(db: AsyncSession, user: User) -> Optional[dict]:
    row = await get_row(db, user.id)
    return _admin_view(user, row) if row else None


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
        await db.execute(delete(MkaRosterOverride).where(MkaRosterOverride.email == row.email_seen))  # type: ignore[arg-type]
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
