"""MKA fork: identity-sync endpoints (mounted at /mka/identity). Spec 2026-10-07 section 3.A4.

* ``POST /sync?org_slug=&dry_run=true``  ensure the Mohtamim role + managed groups, then sync every org member that has an
  attribute row. ``dry_run`` (the default) writes nothing and lists the planned changes (user ids only, capped). A real
  run needs ``MKA_IDENTITY_SYNC_ENABLED`` (409 otherwise): the flag is the kill switch for every write.
* ``GET /status?org_slug=``              flag state, managed role id, group count, last applied sync.

Auth is the same as the other admin endpoints (``_resolve_admin``): an ADMIN session of the org, or an org API token bound
to it (a dry run needs the Read-only preset or better, a real run the Full Access preset). Responses are
``Cache-Control: private, no-store``; no email addresses are returned.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.routers.mka_attributes import _resolve_admin
from src.security.auth import get_authenticated_user
from src.services.mka import identity_sync as sync
from src.services.mka.token_rights import TOKEN_READ, TOKEN_WRITE_FULL

router = APIRouter()


@router.post("/sync")
async def api_sync(
    response: Response,
    dry_run: bool = Query(True),
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    admin = await _resolve_admin(
        current_user, org_id, org_slug, db_session, allow_token=True,
        token_right=TOKEN_READ if dry_run else TOKEN_WRITE_FULL,
    )
    if not dry_run and not sync.enabled():
        raise HTTPException(status_code=409, detail="Identity sync is disabled (MKA_IDENTITY_SYNC_ENABLED is not true); run with dry_run=true")
    return await sync.backfill_org(db_session, admin.org_id, dry_run=dry_run)


@router.get("/status")
async def api_status(
    response: Response,
    org_id: Optional[int] = Query(None),
    org_slug: Optional[str] = Query(None),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    admin = await _resolve_admin(current_user, org_id, org_slug, db_session, allow_token=True, token_right=TOKEN_READ)
    return await sync.status(db_session, admin.org_id)
