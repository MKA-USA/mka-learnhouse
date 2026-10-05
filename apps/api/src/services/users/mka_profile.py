"""MKA fork: Majlis / Region profile fields (domain rules).

Single source of truth for the Majlis -> Region mapping and the validation of
the optional profile fields. Pure (no DB); persistence lives further down in
this module's service functions (added in the DB task) and in the router.
"""

import logging
import re
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.mka_user_profile import MkaUserProfile

MAJLIS_TO_REGION: dict[str, str] = {
    # East
    "Baltimore": "East", "Central Jersey": "East", "Harrisburg": "East",
    "North Jersey": "East", "Philadelphia": "East", "Willingboro": "East",
    # Great Lakes
    "Cleveland": "Great Lakes", "Columbus": "Great Lakes", "Dayton": "Great Lakes",
    "Detroit": "Great Lakes", "Indiana": "Great Lakes", "Kentucky": "Great Lakes",
    # Gulf
    "Austin": "Gulf", "Dallas": "Gulf", "Fort Worth": "Gulf", "Houston": "Gulf",
    "Tulsa": "Gulf",
    # Midwest
    "Chicago": "Midwest", "Kansas City": "Midwest", "Milwaukee": "Midwest",
    "Minnesota": "Midwest", "Oshkosh": "Midwest", "Saint Louis": "Midwest",
    "Zion": "Midwest",
    # Muqami
    "Muqami": "Muqami",
    # New York Metro
    "Bronx": "New York Metro", "Brooklyn": "New York Metro",
    "Long Island": "New York Metro", "Queens": "New York Metro",
    # Northeast
    "Albany": "Northeast", "Boston": "Northeast", "Connecticut": "Northeast",
    "Rochester": "Northeast", "Syracuse-Binghamton": "Northeast",
    # Northwest
    "Bay Point": "Northwest", "Portland": "Northwest", "Sacramento": "Northwest",
    "Seattle": "Northwest", "Silicon Valley": "Northwest",
    # Southeast
    "Atlanta": "Southeast", "Charlotte": "Southeast", "Miami": "Southeast",
    "Orlando": "Southeast", "Tennessee": "Southeast",
    # Southwest
    "Las Vegas": "Southwest", "Los Angeles": "Southwest", "Phoenix": "Southwest",
    "Tucson": "Southwest",
    # Virginia
    "North Virginia": "Virginia", "South Virginia": "Virginia",
    "Richmond": "Virginia", "RTP": "Virginia",
}


class Tanzeem(str, Enum):
    KHADIM = "khadim"
    TIFL = "tifl"


_MOBILE_RE = re.compile(r"^(?:\+?1)?([2-9][0-9]{2})([2-9][0-9]{2})([0-9]{4})$")
_AMC_RE = re.compile(r"^[0-9]{1,15}$")  # ASCII digits only (no unicode digits)


def region_for(majlis: str) -> str:
    return MAJLIS_TO_REGION[majlis]


def normalize_mobile(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("Enter a valid US mobile number")
    stripped = raw.strip()
    if not stripped:
        return None
    if re.search(r"[A-Za-z]", stripped):
        raise ValueError("Enter a valid US mobile number")
    compact = re.sub(r"[\s().\-]", "", stripped)
    m = _MOBILE_RE.match(compact)
    if not m:
        raise ValueError("Enter a valid US mobile number")
    return "+1" + "".join(m.groups())


def normalize_amc_id(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("AMC ID must contain digits only")
    stripped = raw.strip()
    if not stripped:
        return None
    if not _AMC_RE.match(stripped):
        raise ValueError("AMC ID must contain digits only")
    return stripped


class MkaProfileIn(BaseModel):
    """Client-supplied profile. Unknown keys (e.g. `region`) are ignored."""

    model_config = ConfigDict(extra="ignore")

    majlis: str
    mobile: Optional[str] = None
    amc_id: Optional[str] = None
    tanzeem: Optional[str] = None

    @field_validator("majlis")
    @classmethod
    def _majlis(cls, v: str) -> str:
        v = (v or "").strip()
        if v not in MAJLIS_TO_REGION:
            raise ValueError("Select a valid Majlis")
        return v

    @field_validator("mobile", mode="before")
    @classmethod
    def _mobile(cls, v):
        return normalize_mobile(v)

    @field_validator("amc_id", mode="before")
    @classmethod
    def _amc(cls, v):
        return normalize_amc_id(v)

    @field_validator("tanzeem", mode="before")
    @classmethod
    def _tanzeem(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        try:
            return Tanzeem(str(v).strip().lower()).value
        except ValueError:
            raise ValueError("Tanzeem must be Khadim or Tifl")


def parse_profile(raw: Optional[dict], *, required: bool) -> Optional[MkaProfileIn]:
    """Validate a signup-time profile dict. Raises 422 with per-field messages."""
    if raw is None:
        if required:
            raise HTTPException(
                status_code=422,
                detail=[{"field": "majlis", "message": "Majlis is required", "msg": "Majlis is required"}],
            )
        return None
    try:
        return MkaProfileIn.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "field": ".".join(str(p) for p in err["loc"]),
                    "message": err["msg"].removeprefix("Value error, "),
                    # `msg` mirrors `message` so upstream's getErrorMessage (reads
                    # `msg`) shows the real text instead of a generic banner.
                    "msg": err["msg"].removeprefix("Value error, "),
                }
                for err in exc.errors()
            ],
        )


def options_payload() -> dict:
    return {
        "majlis": [
            {"name": name, "region": MAJLIS_TO_REGION[name]}
            for name in sorted(MAJLIS_TO_REGION)
        ],
        "tanzeem": [
            {"value": Tanzeem.KHADIM.value, "label": "Khadim"},
            {"value": Tanzeem.TIFL.value, "label": "Tifl"},
        ],
    }


logger = logging.getLogger(__name__)

_AMC_TAKEN = "That AMC ID is already registered"


async def get_profile(db_session: AsyncSession, user_id: int) -> Optional[MkaUserProfile]:
    stmt = select(MkaUserProfile).where(MkaUserProfile.user_id == user_id)
    return (await db_session.execute(stmt)).scalars().first()


async def profile_status(
    db_session: AsyncSession, user_id: int, *, include_attributes: bool = False
) -> dict:
    """Profile as shown to the user. ``include_attributes`` is ONLY for the GDPR export:
    identity attributes (override, audit...) must never reach the learner-facing routes."""
    row = await get_profile(db_session, user_id)
    if row is None:
        out: dict = {"complete": False}
    else:
        out = {
            "complete": True,
            "majlis": row.majlis,
            "region": row.region,
            "mobile": row.mobile,
            "amc_id": row.amc_id,
            "tanzeem": row.tanzeem,
        }
    if include_attributes:
        from src.services.mka.attributes import export_attributes  # lazy: avoids an import cycle

        attrs = await export_attributes(db_session, user_id)
        if attrs is not None:
            out["mka_attributes"] = attrs
    return out


async def delete_profile(db_session: AsyncSession, user_id: int) -> None:
    """Delete the user's profile row (GDPR anonymize). Does NOT commit: it must
    run inside the caller's transaction so the scrub is atomic.

    Hard-deleting a user needs no call to this: the FK cascades in the DB.
    """
    from src.services.mka.attributes import delete_attributes  # lazy: avoids an import cycle

    await db_session.execute(
        delete(MkaUserProfile).where(MkaUserProfile.user_id == user_id)  # type: ignore[arg-type]
    )
    await delete_attributes(db_session, user_id)


async def _amc_taken(
    db_session: AsyncSession, amc_id: Optional[str], exclude_user_id: Optional[int]
) -> bool:
    if not amc_id:
        return False
    stmt = select(MkaUserProfile.user_id).where(MkaUserProfile.amc_id == amc_id)
    if exclude_user_id is not None:
        stmt = stmt.where(MkaUserProfile.user_id != exclude_user_id)
    return (await db_session.execute(stmt)).first() is not None


async def upsert_profile(
    db_session: AsyncSession,
    user_id: int,
    data: MkaProfileIn,
    *,
    actor: Literal["self", "admin"] = "self",
) -> MkaUserProfile:
    """Full-replace upsert of a profile row.

    AMC ID is admin-managed once set (Salesforce will later be the source of
    truth): with actor="self", if the stored row already has an amc_id it is
    KEPT regardless of data.amc_id (no error); a first-time amc_id is allowed.
    actor="admin" may set, change and clear it. Default is "self" (safe).
    """
    row = await get_profile(db_session, user_id)
    if actor == "self" and row is not None and row.amc_id is not None:
        data = data.model_copy(update={"amc_id": row.amc_id})
    if await _amc_taken(db_session, data.amc_id, exclude_user_id=user_id):
        raise HTTPException(status_code=409, detail=_AMC_TAKEN)
    now = str(datetime.now())
    if row is None:
        row = MkaUserProfile(user_id=user_id, created_at=now)
    row.majlis = data.majlis
    row.region = region_for(data.majlis)
    row.mobile = data.mobile
    row.amc_id = data.amc_id
    row.tanzeem = data.tanzeem
    row.updated_at = now
    db_session.add(row)
    try:
        await db_session.commit()
    except IntegrityError:
        await db_session.rollback()
        if await _amc_taken(db_session, data.amc_id, exclude_user_id=user_id):
            raise HTTPException(status_code=409, detail=_AMC_TAKEN)
        raise
    await db_session.refresh(row)
    return row


async def validate_signup_profile(
    db_session: AsyncSession, raw: Optional[dict], is_oauth: bool
) -> Optional[MkaProfileIn]:
    """Run BEFORE the user row exists. OAuth users may omit it (the gate collects it)."""
    data = parse_profile(raw, required=not is_oauth)
    if data is not None and await _amc_taken(db_session, data.amc_id, exclude_user_id=None):
        raise HTTPException(status_code=409, detail=_AMC_TAKEN)
    return data


async def save_signup_profile(
    db_session: AsyncSession, user, data: Optional[MkaProfileIn]
) -> None:
    """Run right after the user commit.

    The account already exists at this point, so an AMC-ID race (409) must not
    surface as a signup error; the profile gate collects the profile later.
    Any other failure propagates.
    """
    if data is None:
        return
    user_id = user.id  # read before upsert_profile: its rollback() expires `user`
    try:
        await upsert_profile(db_session, user_id, data)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        # The IntegrityError path rolled back, expiring `user`; the caller keeps
        # using it (org link, UserRead), so reload it before returning.
        await db_session.refresh(user)
        logger.warning(
            "MKA profile not saved at signup (conflict); user %s left to the profile gate",
            user_id,
        )
