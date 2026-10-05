"""MKA fork: seam C cron endpoint, mounted under /mka/automation by ``routers/mka_automation.py``.

``POST /reminders/run`` is called by the external scheduler (GitHub Actions) with ``X-MKA-Cron-Secret``. It is NOT an
org-token or session endpoint: ``require_cron_secret`` is the only gate (503 when the secret is unset, 401 otherwise).
The response carries counts only: no addresses, names or answers.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.services.mka import automation_reminders as reminders
from src.services.mka.automation_auth import require_cron_secret

router = APIRouter()


@router.post("/reminders/run", dependencies=[Depends(require_cron_secret)])
async def api_run_reminders(
    response: Response,
    dry_run: bool = Query(True, description="Preview only (default). A real send needs dry_run=false."),
    kind: Literal["reminder", "digest", "all"] = Query("all"),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Decide from the schedule whether today is a reminder day / Monday and (dry-)run it for every org."""
    response.headers["Cache-Control"] = "private, no-store"
    return await reminders.run_all(db_session, dry_run=dry_run, kind=kind)
