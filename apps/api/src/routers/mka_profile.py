"""MKA fork: Majlis/Region profile endpoints (mounted at /mka/profile)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.user_organizations import UserOrganization
from src.db.users import APITokenUser, SuperadminAPITokenUser, User
from src.security.auth import get_authenticated_user
from src.security.org_auth import get_user_org
from src.security.rbac.constants import is_admin
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
    null optional fields (mobile, tanzeem) clear the stored values. AMC ID: may be
    set once; when one is already stored it is kept (admin-managed), whatever is
    submitted."""
    uid = _uid(current_user)
    await upsert_profile(db_session, uid, body)
    return await profile_status(db_session, uid)


async def _authorize_target(
    caller: int, user_id: int, org_id: int, db_session: AsyncSession
) -> None:
    """Shared authz + existence check for the admin profile endpoints.

    Order matters: 403 before any lookup of the target (non-admins learn
    nothing), then 404 for non-members / unknown users.
    """
    superadmin = await is_user_superadmin(caller, db_session)
    if not superadmin:
        caller_org = await get_user_org(caller, org_id, db_session)
        if caller_org is None or not is_admin(caller_org.role_id):
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
    if await db_session.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")


@router.get("/user/{user_id}")
async def api_get_user(
    user_id: int,
    org_id: int = Query(...),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Read a user's profile (same authorization as PUT: org ADMINS of `org_id`
    or superadmins). PUT is a FULL REPLACE, so an editor must GET this first,
    change the fields it wants, then PUT the full object back."""
    await _authorize_target(_uid(current_user), user_id, org_id, db_session)
    return await profile_status(db_session, user_id)


@router.put("/user/{user_id}")
async def api_put_user(
    user_id: int,
    body: MkaProfileIn,
    org_id: int = Query(...),
    current_user=Depends(get_authenticated_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    """FULL REPLACE of a user's profile: majlis is required; omitted or null
    optional fields (mobile, amc_id, tanzeem) CLEAR the stored values (admins may
    set, change and clear the AMC ID; uniqueness still applies -> 409). GET the
    profile first, then PUT the complete object. Org ADMINS (not maintainers)
    may edit members of the org named by `org_id`; superadmins may edit anyone."""
    await _authorize_target(_uid(current_user), user_id, org_id, db_session)
    await upsert_profile(db_session, user_id, body, actor="admin")
    return await profile_status(db_session, user_id)
