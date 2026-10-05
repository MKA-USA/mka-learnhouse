"""MKA fork: compliance automation endpoints (mounted at /mka/automation). Spec 2026-10-05.

IMPORTANT: this router is mounted WITHOUT a router-level auth dependency (see ``router.py``). Every endpoint
authenticates itself, because the callers differ:

* ``GET /status``           org ADMIN session or an org API token with Read-only-or-better rights
                            (``token_rights.TOKEN_READ``), via the same ``_resolve_admin`` as /mka/attributes.
* webhook receiver (seam B) HMAC signature of the raw body (``automation_auth.verify_webhook_signature``).
* cron endpoints (seam C)   ``X-MKA-Cron-Secret`` (``automation_auth.require_cron_secret``).

The org is never taken on trust: sessions must be admins of the ``org_id`` they pass, tokens are bound to their own
org. Responses are ``Cache-Control: private, no-store`` and carry no secrets and no recipient addresses.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.mka_automation import MkaAutomationEvent, MkaAutomationSendLog
from src.routers.mka_attributes import _resolve_admin
from src.security.auth import get_authenticated_user
from src.services.mka import automation_config as cfg
from src.services.mka.token_rights import TOKEN_READ

router = APIRouter()


async def _counts(db: AsyncSession, column, org_column, org_id: int) -> dict:
    rows = (await db.execute(select(column, func.count()).where(org_column == org_id).group_by(column))).all()
    return {str(key): int(n) for key, n in rows}


@router.get("/status")
async def api_status(
    response: Response,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Which automation flags are on, whether test mode is on (masked address) and send-log / event counts."""
    response.headers["Cache-Control"] = "private, no-store"
    admin = await _resolve_admin(current_user, org_id, org_slug, db_session, allow_token=True, token_right=TOKEN_READ)
    send_status = await _counts(db_session, MkaAutomationSendLog.status, MkaAutomationSendLog.org_id, admin.org_id)
    test_rows = (
        await db_session.execute(
            select(func.count()).where(
                MkaAutomationSendLog.org_id == admin.org_id, MkaAutomationSendLog.test_mode == True  # noqa: E712
            )
        )
    ).scalar_one()
    event_status = await _counts(db_session, MkaAutomationEvent.status, MkaAutomationEvent.org_id, admin.org_id)
    return {
        "config": cfg.status_snapshot(),
        "send_log": {"total": sum(send_status.values()), "by_status": send_status, "test_mode_rows": int(test_rows)},
        "events": {"total": sum(event_status.values()), "by_status": event_status},
    }


# --- seam B: webhook/receipts ---
from src.routers.mka_automation_receipts import router as _receipts_router  # noqa: E402

router.include_router(_receipts_router)
