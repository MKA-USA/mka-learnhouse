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

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.mka_automation import MkaAutomationEvent, MkaAutomationSendLog, utcnow
from src.routers.mka_attributes import _resolve_admin
from src.security.auth import get_authenticated_user
from src.services.mka import automation_config as cfg
from src.services.mka.automation_send import current_mode_is_test, failing_addresses, stale_claim_cutoff
from src.services.mka.token_rights import TOKEN_READ

router = APIRouter()

AUTOENROLL_ERROR_WINDOW_DAYS = 7


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
    """Which automation flags are on, whether test mode is on (masked address), send-log / event counts and the number
    of recent auto-enrol errors (``autoenroll.errors_recent``: should be 0 after a test login)."""
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
    # claims left 'queued' past the lease: a crash between claim and send (review M2). The send function takes a
    # stale claim over once; anything still listed here after a run needs a look.
    stale_queued = (
        await db_session.execute(
            select(func.count()).where(
                MkaAutomationSendLog.org_id == admin.org_id,
                MkaAutomationSendLog.status == "queued",
                MkaAutomationSendLog.created_at < stale_claim_cutoff(utcnow()),
            )
        )
    ).scalar_one()
    failing = await failing_addresses(db_session, admin.org_id, test_mode=current_mode_is_test(), now=utcnow())
    failing_count = sum(1 for n in failing.values() if n >= cfg.reminder_max_address_failures())
    event_status = await _counts(db_session, MkaAutomationEvent.status, MkaAutomationEvent.org_id, admin.org_id)
    # Auto-enrol fails open (login must never break), so a broken enrolment is only visible here (review M1).
    enrol_errors = (
        await db_session.execute(
            select(func.count()).where(
                MkaAutomationEvent.org_id == admin.org_id,
                MkaAutomationEvent.event == "autoenroll",
                MkaAutomationEvent.status == "error",
                MkaAutomationEvent.received_at >= utcnow() - timedelta(days=AUTOENROLL_ERROR_WINDOW_DAYS),
            )
        )
    ).scalar_one()
    return {
        "config": cfg.status_snapshot(),
        "send_log": {"total": sum(send_status.values()), "by_status": send_status, "test_mode_rows": int(test_rows),
                     "stale_queued": int(stale_queued),
                     "failing_addresses": failing_count},
        "events": {"total": sum(event_status.values()), "by_status": event_status},
        "autoenroll": {"errors_recent": int(enrol_errors), "window_days": AUTOENROLL_ERROR_WINDOW_DAYS},
    }


# --- seam B: webhook/receipts ---
from src.routers.mka_automation_receipts import router as _receipts_router  # noqa: E402

router.include_router(_receipts_router)

# --- seam C: reminders ---
from src.routers.mka_automation_reminders import router as _reminders_router  # noqa: E402

router.include_router(_reminders_router)
