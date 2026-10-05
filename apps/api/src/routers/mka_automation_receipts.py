"""MKA fork: seam B endpoints (webhook receiver + receipts sweep), included by ``routers/mka_automation.py``.

* ``POST /webhooks/learnhouse``: NO session; the HMAC signature of the RAW body is the authentication. The raw bytes
  are read and verified BEFORE any JSON parsing. Bad/missing signature: 401 with an empty body.
* ``POST /receipts/sweep``: cron secret (``X-MKA-Cron-Secret``), dry run by default, per-run send cap.
"""

import json
import logging

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.services.mka import automation_config as cfg
from src.services.mka import automation_receipts as receipts
from src.services.mka.automation_auth import require_cron_secret, verify_webhook_signature
from src.services.mka.automation_send import SendBudget

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_BODY_BYTES = 64 * 1024  # LearnHouse payloads are a few hundred bytes


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


@router.post("/webhooks/learnhouse")
async def learnhouse_webhook(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return Response(status_code=413)
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():  # count as we go: never buffer past the cap (+ one chunk)
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            return Response(status_code=413)
        chunks.append(chunk)
    raw = b"".join(chunks)  # the signature covers exactly these bytes
    if not verify_webhook_signature(raw, request.headers.get("X-Webhook-Signature"), cfg.webhook_secret()):
        logger.warning("automation webhook: bad or missing signature")
        return Response(status_code=401)

    # authenticated from here on
    if not cfg.feature_enabled("receipts"):
        return JSONResponse({"status": "disabled"}, headers={"Cache-Control": "no-store"})
    try:
        delivery = receipts.parse_delivery(json.loads(raw))
    except (ValueError, UnicodeDecodeError, RecursionError):  # BadPayload is a ValueError; JSON errors too
        logger.warning("automation webhook: unusable or stale body")
        return JSONResponse({"status": "rejected"}, status_code=400, headers={"Cache-Control": "no-store"})
    result = await receipts.handle_delivery(db_session, delivery)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.post("/receipts/sweep", dependencies=[Depends(require_cron_secret)])
async def receipts_sweep(
    response: Response,
    dry_run: bool = Query(True),
    days: int = Query(7, ge=1, le=receipts.MAX_SWEEP_DAYS),
    org_id: int | None = Query(None),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Send the sign-off receipts the webhook never delivered (3 attempts, then LearnHouse drops the event)."""
    _no_store(response)
    if not dry_run and not cfg.feature_enabled("receipts"):
        return {"status": "disabled", "dry_run": False}
    summary = await receipts.run_sweep(db_session, dry_run=dry_run, days=days, budget=SendBudget(), org_id=org_id)
    return {"status": "ok", **summary}
