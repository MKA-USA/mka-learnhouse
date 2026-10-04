"""MKA fork: Majlis/Region profile endpoints (mounted at /mka/profile)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.user_organizations import UserOrganization
from src.db.users import APITokenUser, SuperadminAPITokenUser
from src.security.auth import get_authenticated_user
from src.security.org_auth import is_org_admin
from src.security.superadmin import is_user_superadmin
from src.services.users.mka_profile import (
    MkaProfileIn,
    options_payload,
    profile_status,
    upsert_profile,
)

router = APIRouter()


def _uid(current_user) -> int:
    # API-token principals carry a token id in `.id`, not a user id: refuse.
    if isinstance(current_user, (APITokenUser, SuperadminAPITokenUser)):
        raise HTTPException(status_code=403, detail="A user session is required")
    uid = getattr(current_user, "id", None)
    if not uid:
        raise HTTPException(status_code=403, detail="A user session is required")
    return uid


@router.get("/options")
async def api_options() -> dict:
    """Public: the signup page needs the Majlis list before login."""
    return options_payload()


@router.get("/me")
async def api_get_me(
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    return await profile_status(db_session, _uid(current_user))


@router.put("/me")
async def api_put_me(
    body: MkaProfileIn,
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Full replace of the caller's profile: majlis is required; omitted or
    null optional fields (mobile, amc_id, tanzeem) clear the stored values."""
    uid = _uid(current_user)
    await upsert_profile(db_session, uid, body)
    return await profile_status(db_session, uid)


@router.put("/user/{user_id}")
async def api_put_user(
    user_id: int,
    body: MkaProfileIn,
    org_id: int = Query(...),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Full replace of a user's profile (majlis required; omitted or null
    optional fields clear stored values). Org admins may edit members of the
    org named by `org_id`; superadmins may edit anyone."""
    caller = _uid(current_user)
    if not await is_user_superadmin(caller, db_session):
        # 403 before any membership lookup so non-admins learn nothing.
        if not await is_org_admin(caller, org_id, db_session):
            raise HTTPException(status_code=403, detail="Admin access required")
        member = (
            await db_session.execute(
                select(UserOrganization).where(
                    UserOrganization.user_id == user_id,
                    UserOrganization.org_id == org_id,
                )
            )
        ).scalars().first()
        if member is None:
            raise HTTPException(status_code=404, detail="User not found in this organization")
    await upsert_profile(db_session, user_id, body)
    return await profile_status(db_session, user_id)
