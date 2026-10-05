"""Staff-only moderation flag API and the per-org AI-moderation toggle.

Flags are advisory review aids and are never exposed to non-staff users or to
the author of the flagged content.
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.moderation_flags import (
    AIModerationSettingsRead,
    AIModerationSettingsUpdate,
    ContentType,
    FlagItemsResponse,
    FlagListResponse,
    FlagRead,
    FlagStatusUpdate,
)
from src.db.users import PublicUser
from src.security.auth import get_authenticated_user
from src.services.moderation_ai import service, settings

# /api/v1/moderation-flags/...
router = APIRouter()
# /api/v1/orgs/{org_id}/config/ai-moderation (mounted under the "/orgs" prefix)
org_settings_router = APIRouter()


def _staff_user(user=Depends(get_authenticated_user)):
    # API tokens carry no human reviewer identity; staff actions need a person.
    if not isinstance(user, PublicUser):
        raise HTTPException(status_code=403, detail="Moderation staff only")
    return user


@router.get(
    "/orgs/{org_id}",
    response_model=FlagListResponse,
    summary="List moderation flags (staff only)",
)
async def api_list_flags(
    request: Request,
    org_id: int,
    status: Literal["open", "reviewed", "dismissed", "all"] = "open",
    content_type: Optional[ContentType] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: PublicUser = Depends(_staff_user),
    db_session: AsyncSession = Depends(get_db_session),
):
    _, scope = await service.require_moderation_scope(request, user, org_id, db_session)
    items, total = await service.list_flags(
        org_id,
        db_session,
        status=status,
        content_type=content_type,
        limit=limit,
        offset=offset,
        requester=user,
        scope=scope,
    )
    return FlagListResponse(items=items, total=total)


@router.get(
    "/orgs/{org_id}/by-content",
    response_model=FlagItemsResponse,
    summary="Flags for one piece of content (staff only)",
)
async def api_flags_by_content(
    request: Request,
    org_id: int,
    content_uuid: str = Query(..., min_length=1, max_length=100),
    content_type: Optional[ContentType] = None,
    user: PublicUser = Depends(_staff_user),
    db_session: AsyncSession = Depends(get_db_session),
):
    # Instructors may read flags on submissions of courses they teach.
    _, scope = await service.require_flag_access(request, user, org_id, db_session, assignment_scope=True)
    return FlagItemsResponse(
        items=await service.flags_by_content(
            org_id,
            content_type,
            content_uuid,
            db_session,
            requester=user,
            request=request,
            is_staff=scope is not None,
            scope=scope,
        )
    )


@router.get(
    "/orgs/{org_id}/by-user/{user_uuid}",
    response_model=FlagItemsResponse,
    summary="Flags on one user's content (staff only)",
)
async def api_flags_by_user(
    request: Request,
    org_id: int,
    user_uuid: str,
    user: PublicUser = Depends(_staff_user),
    db_session: AsyncSession = Depends(get_db_session),
):
    _, scope = await service.require_flag_access(request, user, org_id, db_session, assignment_scope=True)
    return FlagItemsResponse(
        items=await service.flags_by_user(
            org_id,
            user_uuid,
            db_session,
            requester=user,
            request=request,
            is_staff=scope is not None,
            scope=scope,
        )
    )


@router.patch(
    "/{flag_uuid}",
    response_model=FlagRead,
    summary="Mark a flag reviewed, dismissed, or reopen it (staff only)",
)
async def api_update_flag(
    request: Request,
    flag_uuid: str,
    body: FlagStatusUpdate,
    user: PublicUser = Depends(_staff_user),
    db_session: AsyncSession = Depends(get_db_session),
):
    return await service.update_flag_status(request, flag_uuid, body.status, user, db_session)


@org_settings_router.get(
    "/{org_id}/config/ai-moderation",
    response_model=AIModerationSettingsRead,
    summary="Read the AI content moderation setting (admin only)",
)
async def api_get_ai_moderation(
    org_id: int,
    user: PublicUser = Depends(_staff_user),
    db_session: AsyncSession = Depends(get_db_session),
):
    from src.security.org_auth import require_org_admin

    await require_org_admin(user.id, org_id, db_session)  # type: ignore[arg-type]
    return await settings.get_ai_moderation_settings(org_id, db_session)


@org_settings_router.put(
    "/{org_id}/config/ai-moderation",
    response_model=AIModerationSettingsRead,
    summary="Enable or disable AI content moderation (admin only)",
    description=(
        "Off by default. When on, text from discussions, assignment submissions "
        "and profile fields is sent to a third-party AI provider for advisory "
        "review. Flags are visible to staff only and never affect grades."
    ),
)
async def api_update_ai_moderation(
    org_id: int,
    body: AIModerationSettingsUpdate,
    user: PublicUser = Depends(_staff_user),
    db_session: AsyncSession = Depends(get_db_session),
):
    from src.security.org_auth import require_org_admin

    await require_org_admin(user.id, org_id, db_session)  # type: ignore[arg-type]
    return await settings.update_ai_moderation_settings(org_id, body.enabled, list(body.surfaces) if body.surfaces else None, db_session)
