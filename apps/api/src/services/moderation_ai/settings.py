"""Org opt-in for AI moderation.

The per-org toggle lives in the org config JSON blob (no migration):
v2 -> ``admin_toggles.moderation_ai``; v1 -> ``features.moderation_ai``.
It is OFF by default and, for moderation only, REPLACES the YAML
``jev_config.allowed_org_ids`` allow-list (that list still gates the other Jev
features). The platform-level gate (Jev enabled + API key) still applies.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from config.config import get_learnhouse_config
from src.db.moderation_flags import CONTENT_TYPES, AIModerationSettingsRead
from src.db.organization_config import ModerationAIAdminToggle, OrganizationConfig
from src.db.organizations import Organization

logger = logging.getLogger(__name__)


def jev_available() -> bool:
    """Platform gate: Jev enabled in deployment config and an API key present."""
    try:
        cfg = get_learnhouse_config().jev_config
    except Exception:  # noqa: BLE001
        return False
    return bool(cfg is not None and cfg.enabled and cfg.api_key)


def _is_v2(config: dict) -> bool:
    return str(config.get("config_version", "1.0")).startswith("2")


def read_toggle(config: dict | None) -> ModerationAIAdminToggle:
    """Parse the org's moderation toggle from a raw config blob (never raises)."""
    config = config or {}
    try:
        if _is_v2(config):
            raw = (config.get("admin_toggles") or {}).get("moderation_ai") or {}
        else:
            raw = (config.get("features") or {}).get("moderation_ai") or {}
        return ModerationAIAdminToggle(**raw)
    except Exception:  # noqa: BLE001 - malformed blob == opted out
        return ModerationAIAdminToggle()


def org_opted_in(config: dict | None, content_type: str | None = None) -> bool:
    """True if the org enabled moderation (and the surface, if one is given)."""
    toggle = read_toggle(config)
    if not toggle.enabled:
        return False
    if content_type and toggle.surfaces:
        return content_type in toggle.surfaces
    return True


async def load_org_config_dict(org_id: int, db_session: AsyncSession) -> dict:
    """Org config blob via the shared Redis read-aside cache, then the DB."""
    try:
        from src.services.orgs.cache import get_cached_org_config

        raw = get_cached_org_config(org_id)
        if isinstance(raw, dict) and isinstance(raw.get("config"), dict):
            return raw["config"]
    except Exception:  # noqa: BLE001
        pass
    row = (
        await db_session.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == org_id))
    ).scalars().first()
    return dict(row.config or {}) if row is not None else {}


async def moderation_enabled(
    org_id: int | None,
    db_session: AsyncSession | None = None,
    content_type: str | None = None,
) -> bool:
    """Platform gate AND org opt-in. Fail-closed (False) on any error."""
    if org_id is None or not jev_available():
        return False
    try:
        if db_session is not None:
            config = await load_org_config_dict(org_id, db_session)
        else:
            from src.services.moderation_ai.scheduler import session_factory

            async with session_factory()() as session:
                config = await load_org_config_dict(org_id, session)
        return org_opted_in(config, content_type)
    except Exception as exc:  # noqa: BLE001
        logger.warning("moderation_enabled check failed (%s)", type(exc).__name__)
        return False


def settings_read(config: dict | None) -> AIModerationSettingsRead:
    toggle = read_toggle(config)
    return AIModerationSettingsRead(
        enabled=toggle.enabled,
        surfaces=list(toggle.surfaces) if toggle.surfaces else list(CONTENT_TYPES),
        provider_available=jev_available(),
    )


async def get_ai_moderation_settings(org_id: int, db_session: AsyncSession) -> AIModerationSettingsRead:
    org = (await db_session.execute(select(Organization).where(Organization.id == org_id))).scalars().first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return settings_read(await load_org_config_dict(org_id, db_session))


async def update_ai_moderation_settings(
    org_id: int,
    enabled: bool,
    surfaces: Optional[list[str]],
    db_session: AsyncSession,
) -> AIModerationSettingsRead:
    """Persist the toggle. Caller must already have verified org-admin rights."""
    org = (await db_session.execute(select(Organization).where(Organization.id == org_id))).scalars().first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    org_config = (
        await db_session.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == org.id))
    ).scalars().first()
    if org_config is None:
        raise HTTPException(status_code=404, detail="Organization config not found")

    picked = [s for s in (surfaces or []) if s in CONTENT_TYPES]
    # Empty list == all surfaces; store None so "all" survives new surfaces.
    toggle = ModerationAIAdminToggle(
        enabled=bool(enabled),
        surfaces=picked if picked and len(set(picked)) < len(CONTENT_TYPES) else None,
    )
    data = json.loads(toggle.model_dump_json())

    updated = json.loads(json.dumps(org_config.config or {}))
    if _is_v2(updated):
        updated.setdefault("admin_toggles", {})["moderation_ai"] = data
    else:
        updated.setdefault("features", {})["moderation_ai"] = data

    org_config.config = updated
    org_config.update_date = str(datetime.now())
    db_session.add(org_config)
    await db_session.commit()
    await db_session.refresh(org_config)

    try:
        from src.services.orgs.cache import invalidate_org_config_cache

        invalidate_org_config_cache(org.id)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        pass

    return settings_read(updated)
