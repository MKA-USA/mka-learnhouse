"""MKA fork: unauthenticated schema health (mounted at /mka/health).

``GET /schema`` -> ``{"ok": bool, "missing": <count>, "alembic_at_head": bool}``. Counts only: no table or column names
(they stay in the server log as ``MKA_SCHEMA_DRIFT``). Result is cached briefly so the public endpoint cannot be used
to hammer the catalog.
"""

import logging
import time

from fastapi import APIRouter, Response

from src.core.events.database import engine
from src.services.mka import schema_drift

router = APIRouter()
log = logging.getLogger(__name__)
_CACHE_TTL = 15.0
_cache: dict = {"at": 0.0, "value": None}


def _check(sync_conn) -> dict:
    drift = schema_drift.compute_drift(sync_conn)
    at_head = schema_drift.alembic_at_head(sync_conn)
    return {"ok": drift.ok and at_head, "missing": drift.count, "alembic_at_head": at_head}


@router.get("/schema")
async def schema_health(response: Response):
    response.headers["Cache-Control"] = "no-store"
    now = time.monotonic()
    if _cache["value"] is not None and now - _cache["at"] < _CACHE_TTL:
        return _cache["value"]
    try:
        async with engine.connect() as conn:
            value = await conn.run_sync(_check)
    except Exception:  # noqa: BLE001
        log.exception("schema health check failed")
        response.status_code = 503
        return {"ok": False, "missing": -1, "alembic_at_head": False}
    _cache.update(at=now, value=value)
    return value
