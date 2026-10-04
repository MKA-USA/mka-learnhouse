"""MKA fork: Majlis / Region profile fields (domain rules).

Single source of truth for the Majlis -> Region mapping and the validation of
the optional profile fields. Pure (no DB); persistence lives further down in
this module's service functions (added in the DB task) and in the router.
"""

import re
from enum import Enum
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

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
                detail=[{"field": "majlis", "message": "Majlis is required"}],
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
