# MKA Profile Fields (Capture & Store) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every new LearnHouse user (email, invite, org-less, Google) ends up with a Majlis and a server-derived Region, plus optional mobile / AMC ID / Tanzeem, stored in a fork-only table; existing and Google users are hard-gated until Majlis is set.

**Architecture:** A fork-only side table `mka_user_profile` (1:1 with `user`) plus a fork-only service module holding the 52-Majlis→11-Region mapping and validation. Upstream files receive only 1–3 line `# MKA fork` hooks. A fork-only FastAPI router (`/mka/profile`) serves options and profile read/write; a fork-only non-dismissible gate component (mounted once in the org layout) collects the profile for Google and existing users. UI is built from LearnHouse's own shadcn/Radix primitives and theme tokens.

**Tech Stack:** FastAPI + SQLModel + Alembic + pytest (in-memory SQLite) · Next.js 16 / React 19 / Tailwind v4 · shadcn `new-york` (Radix) · Formik + Yup · react-query · `cmdk` via shadcn `command`.

**Spec:** `docs/superpowers/specs/2026-10-04-mka-profile-fields-design.md` (read it first; this plan corrects three details of it, see "Spec corrections" below).

## Spec corrections discovered while planning
1. Spec said the profile is written "in the same DB transaction as the user". The real `create_user` commits the user, then the org link, separately. Plan: validate (including AMC conflict pre-check) **before** the user row is created, write the profile row **immediately after** the user commit. If that write ever fails, the gate catches the user on first load.
2. Spec listed a hook in `app/(hub)/layout.tsx`. That layout 404s on oss/ee deployments and is SaaS-only org management; **do not hook it**. The org layout is the only mount point.
3. Spec listed hooks in all three create functions. `create_user_with_invite` calls `create_user`, so only `create_user` and `create_user_without_org` need hooks.

## Global Constraints
- Fork safety: new logic only in new files; upstream files get minimal hooks marked `# MKA fork` (Python) / `// MKA fork` (TS), each logged in `.codebase-memory/upstream-modifications.md` with exact diff. Never modify existing files in `apps/web/components/ui/` (the only allowed change there is the new shadcn `command.tsx`), `apps/api/src/db/users.py` beyond the one `UserCreate` field, `CompleteSignupFields.tsx`, or the org signup-fields service/endpoints.
- Region is always derived server-side; any client-supplied `region` is ignored.
- AMC ID: digits only, stored as string, 1–15 digits, unique when present (NULLs never collide). Non-digit input is rejected, not stripped.
- Mobile: US-only; accepts spaces/dashes/parens and optional `+1`/`1` prefix; must be 10 digits with area code and exchange starting 2–9; stored as `+1XXXXXXXXXX`.
- Tanzeem: `khadim` | `tifl` | null (mutually exclusive). 52 Majlis, 11 Regions.
- Org admins can edit a member's profile (members of orgs they administer); superadmins can edit anyone.
- No new UI primitives: reuse `components/ui/*` (Radix) and the official shadcn `command` component. Theme tokens only (`bg-background`, `text-foreground`, `border-input`, `text-destructive`, `text-muted-foreground`, `ring-ring`, …) — never literal colors like `bg-neutral-50` / `text-red-500`.
- Never run `shadcn add … --overwrite`; decline any proposed `globals.css` token patch; do not pull `react-hook-form`/`zod` (app uses Formik + Yup).
- New user-visible strings in MKA components are English literals (adding keys to upstream locale files would create merge conflicts).
- No Alembic edits to upstream migrations. New revision id prefixed `mka_`, chained from the real head.
- Branch: confirm a feature branch with the user before the first commit (do not commit to `dev` unasked).

## Review Focus
- AMC ID entered with spaces/letters/leading zeros (`" 00123 "`, `"12a"`): trimmed, letters rejected with a field error, leading zeros preserved. (Task 1)
- Two users submit the same AMC ID concurrently / one is already registered: second gets 409 and no orphan user row when pre-check catches it. (Tasks 2, 3)
- Client posts `region`, `extra_metadata`, or unknown keys inside `mka_profile`: ignored, never stored. (Tasks 1, 3, 6)
- Google user lands with no profile: gate appears, cannot be dismissed with Esc / outside click, has a sign-out escape; Popover list is not hidden behind the Dialog (z-index). (Task 7)
- Org admin edits a user outside their org / a normal member edits someone else: 403/404, no write. (Task 4)

---

### Task 1: Fork-only domain module (mapping + validation), pure and DB-free

**Files:**
- Create: `apps/api/src/services/users/mka_profile.py`
- Test: `apps/api/src/tests/services/test_mka_profile_domain.py`

**Interfaces:**
- Produces:
  - `MAJLIS_TO_REGION: dict[str, str]` (52 entries)
  - `class Tanzeem(str, Enum)`: `KHADIM="khadim"`, `TIFL="tifl"`
  - `normalize_mobile(raw: str | None) -> str | None` (raises `ValueError`)
  - `normalize_amc_id(raw: str | None) -> str | None` (raises `ValueError`)
  - `region_for(majlis: str) -> str`
  - `class MkaProfileIn(BaseModel)`: `majlis: str`, `mobile/amc_id/tanzeem: Optional[str]`, validators normalize; unknown keys ignored
  - `parse_profile(raw: dict | None, *, required: bool) -> MkaProfileIn | None` (raises `HTTPException(422, detail=[{"field","message"}])`)
  - `options_payload() -> dict` (`{"majlis":[{"name","region"}...],"tanzeem":[{"value","label"}...]}` sorted by name)

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/src/tests/services/test_mka_profile_domain.py
import pytest
from fastapi import HTTPException

from src.services.users.mka_profile import (
    MAJLIS_TO_REGION,
    MkaProfileIn,
    normalize_amc_id,
    normalize_mobile,
    options_payload,
    parse_profile,
    region_for,
)

EXPECTED_REGIONS = {
    "East", "Great Lakes", "Gulf", "Midwest", "Muqami", "New York Metro",
    "Northeast", "Northwest", "Southeast", "Southwest", "Virginia",
}


def test_mapping_has_52_majlis_and_11_regions():
    assert len(MAJLIS_TO_REGION) == 52
    assert set(MAJLIS_TO_REGION.values()) == EXPECTED_REGIONS


@pytest.mark.parametrize("majlis,region", [
    ("Baltimore", "East"), ("Detroit", "Great Lakes"), ("Fort Worth", "Gulf"),
    ("Zion", "Midwest"), ("Muqami", "Muqami"), ("Queens", "New York Metro"),
    ("Syracuse-Binghamton", "Northeast"), ("Silicon Valley", "Northwest"),
    ("Tennessee", "Southeast"), ("Las Vegas", "Southwest"), ("RTP", "Virginia"),
    ("North Virginia", "Virginia"),
])
def test_region_for_spot_checks(majlis, region):
    assert region_for(majlis) == region


@pytest.mark.parametrize("raw,expected", [
    ("(703) 234-0142", "+17032340142"),
    ("703.234.0142", "+17032340142"),
    ("+1 703 234 0142", "+17032340142"),
    ("1-703-234-0142", "+17032340142"),
    ("7032340142", "+17032340142"),
    ("", None),
    ("   ", None),
    (None, None),
])
def test_normalize_mobile_ok(raw, expected):
    assert normalize_mobile(raw) == expected


@pytest.mark.parametrize("raw", [
    "123", "0032340142", "1032340142", "703 034 0142", "+44 20 7946 0958",
    "703-234-014a", "70323401420",
])
def test_normalize_mobile_rejects(raw):
    with pytest.raises(ValueError):
        normalize_mobile(raw)


@pytest.mark.parametrize("raw,expected", [
    ("12345", "12345"), (" 00123 ", "00123"), ("", None), (None, None),
    ("1" * 15, "1" * 15),
])
def test_normalize_amc_ok(raw, expected):
    assert normalize_amc_id(raw) == expected


@pytest.mark.parametrize("raw", ["12a", "1 2", "-5", "1" * 16, "١٢٣"])
def test_normalize_amc_rejects(raw):
    with pytest.raises(ValueError):
        normalize_amc_id(raw)


def test_profile_in_derives_nothing_and_ignores_unknown_keys():
    p = MkaProfileIn.model_validate(
        {"majlis": "Baltimore", "region": "Midwest", "extra_metadata": {"x": 1}}
    )
    assert p.majlis == "Baltimore"
    assert not hasattr(p, "region")
    assert not hasattr(p, "extra_metadata")


def test_profile_in_tanzeem():
    assert MkaProfileIn(majlis="Zion", tanzeem="Khadim").tanzeem == "khadim"
    assert MkaProfileIn(majlis="Zion", tanzeem="").tanzeem is None
    with pytest.raises(ValueError):
        MkaProfileIn(majlis="Zion", tanzeem="both")


def test_profile_in_rejects_unknown_majlis():
    with pytest.raises(ValueError):
        MkaProfileIn(majlis="Atlantis")


def test_parse_profile_required_missing_is_422():
    with pytest.raises(HTTPException) as e:
        parse_profile(None, required=True)
    assert e.value.status_code == 422
    assert e.value.detail[0]["field"] == "majlis"


def test_parse_profile_optional_missing_is_none():
    assert parse_profile(None, required=False) is None


def test_parse_profile_field_errors_are_clean():
    with pytest.raises(HTTPException) as e:
        parse_profile({"majlis": "Zion", "amc_id": "12a"}, required=True)
    assert e.value.status_code == 422
    assert e.value.detail == [{"field": "amc_id", "message": "AMC ID must contain digits only"}]


def test_options_payload_shape():
    o = options_payload()
    assert len(o["majlis"]) == 52
    assert o["majlis"][0] == {"name": "Albany", "region": "Northeast"}
    assert [t["value"] for t in o["tanzeem"]] == ["khadim", "tifl"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && python -m pytest src/tests/services/test_mka_profile_domain.py -v`
Expected: collection error `ModuleNotFoundError: src.services.users.mka_profile`.

- [ ] **Step 3: Write the implementation**

```python
# apps/api/src/services/users/mka_profile.py
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


_MOBILE_RE = re.compile(r"^(?:\+?1)?([2-9]\d{2})([2-9]\d{2})(\d{4})$")
_AMC_RE = re.compile(r"^[0-9]{1,15}$")  # ASCII digits only (no unicode digits)


def region_for(majlis: str) -> str:
    return MAJLIS_TO_REGION[majlis]


def normalize_mobile(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
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
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && python -m pytest src/tests/services/test_mka_profile_domain.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit** (on the branch agreed with the user)

```bash
git add apps/api/src/services/users/mka_profile.py apps/api/src/tests/services/test_mka_profile_domain.py
git commit -m "feat(profile): add Majlis/Region domain rules and validation"
```

---

### Task 2: Side table model, migration, persistence functions

**Files:**
- Create: `apps/api/src/db/mka_user_profile.py`
- Create: `apps/api/migrations/versions/mka_20261004_user_profile.py`
- Modify (append): `apps/api/src/services/users/mka_profile.py` (persistence functions + imports)
- Test: `apps/api/src/tests/services/test_mka_profile_store.py`

**Interfaces:**
- Consumes: `MkaProfileIn`, `region_for`, `parse_profile` from Task 1.
- Produces (all `async`, first arg `db_session: AsyncSession`):
  - `get_profile(db_session, user_id: int) -> MkaUserProfile | None`
  - `profile_status(db_session, user_id: int) -> dict` → `{"complete": False}` or `{"complete": True, "majlis","region","mobile","amc_id","tanzeem"}`
  - `upsert_profile(db_session, user_id: int, data: MkaProfileIn) -> MkaUserProfile` (409 on AMC conflict)
  - `validate_signup_profile(db_session, raw: dict | None, is_oauth: bool) -> MkaProfileIn | None` (pre-user-creation: parses, enforces required for non-OAuth, pre-checks AMC conflict)
  - `save_signup_profile(db_session, user_id: int, data: MkaProfileIn | None) -> None`

- [ ] **Step 1: Verify table name and existing head (read-only)**

Run:
```bash
cd apps/api && grep -n "class User(UserBase" -A4 src/db/users.py
python3 - <<'E'
import re,glob
revs={};downs=set()
for f in glob.glob('migrations/versions/*.py'):
    s=open(f).read()
    r=re.search(r"^revision\s*(?::[^=]+)?=\s*['\"]([^'\"]+)['\"]",s,re.M)
    if not r: continue
    revs[r.group(1)]=f
    for m in re.finditer(r"^down_revision\s*(?::[^=]+)?=\s*(.+?)(?=^\w|\Z)",s,re.M|re.S):
        downs.update(re.findall(r"['\"]([^'\"]+)['\"]",m.group(1)))
print([r for r in revs if r not in downs])
E
```
Expected: `User` table is `"user"` (SQLModel default; `ForeignKey("user.id")` is used by other models — confirm with `grep -rn 'ForeignKey("user.id"' src/db | head -3`) and the head list is `['b1c2d3e4f5a6']`. If a different single head prints, use it as `down_revision` below. If `alembic` is installed in the API venv, `alembic heads` is the authoritative check — run it too.

- [ ] **Step 2: Write the failing store tests**

```python
# apps/api/src/tests/services/test_mka_profile_store.py
import pytest
from fastapi import HTTPException
from sqlmodel import select

from src.db.mka_user_profile import MkaUserProfile
from src.db.users import User
from src.services.users.mka_profile import (
    MkaProfileIn,
    get_profile,
    profile_status,
    save_signup_profile,
    upsert_profile,
    validate_signup_profile,
)


async def _mk_user(db, n):
    from datetime import datetime
    u = User(
        username=f"u{n}", first_name="U", last_name=str(n), email=f"u{n}@test.com",
        password="x", user_uuid=f"user_u{n}",
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_status_incomplete_without_row(db):
    u = await _mk_user(db, 1)
    assert await profile_status(db, u.id) == {"complete": False}


@pytest.mark.asyncio
async def test_upsert_derives_region_and_round_trips(db):
    u = await _mk_user(db, 1)
    await upsert_profile(
        db, u.id,
        MkaProfileIn(majlis="Baltimore", mobile="(703) 234-0142", amc_id="00123", tanzeem="tifl"),
    )
    s = await profile_status(db, u.id)
    assert s == {
        "complete": True, "majlis": "Baltimore", "region": "East",
        "mobile": "+17032340142", "amc_id": "00123", "tanzeem": "tifl",
    }


@pytest.mark.asyncio
async def test_upsert_updates_and_rederives_region(db):
    u = await _mk_user(db, 1)
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Baltimore"))
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Zion"))
    s = await profile_status(db, u.id)
    assert (s["majlis"], s["region"]) == ("Zion", "Midwest")
    rows = (await db.execute(select(MkaUserProfile))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_duplicate_amc_is_409(db):
    a, b = await _mk_user(db, 1), await _mk_user(db, 2)
    await upsert_profile(db, a.id, MkaProfileIn(majlis="Zion", amc_id="777"))
    with pytest.raises(HTTPException) as e:
        await upsert_profile(db, b.id, MkaProfileIn(majlis="Zion", amc_id="777"))
    assert e.value.status_code == 409
    assert await get_profile(db, b.id) is None


@pytest.mark.asyncio
async def test_same_user_can_resave_own_amc(db):
    a = await _mk_user(db, 1)
    await upsert_profile(db, a.id, MkaProfileIn(majlis="Zion", amc_id="777"))
    await upsert_profile(db, a.id, MkaProfileIn(majlis="Zion", amc_id="777", tanzeem="khadim"))
    assert (await profile_status(db, a.id))["tanzeem"] == "khadim"


@pytest.mark.asyncio
async def test_two_null_amc_ids_do_not_collide(db):
    a, b = await _mk_user(db, 1), await _mk_user(db, 2)
    await upsert_profile(db, a.id, MkaProfileIn(majlis="Zion"))
    await upsert_profile(db, b.id, MkaProfileIn(majlis="Zion"))
    assert (await profile_status(db, a.id))["complete"] and (await profile_status(db, b.id))["complete"]


@pytest.mark.asyncio
async def test_validate_signup_profile_rules(db):
    # non-oauth requires majlis
    with pytest.raises(HTTPException) as e:
        await validate_signup_profile(db, None, is_oauth=False)
    assert e.value.status_code == 422
    # oauth may omit it
    assert await validate_signup_profile(db, None, is_oauth=True) is None
    # valid
    p = await validate_signup_profile(db, {"majlis": "Zion", "region": "East"}, is_oauth=False)
    assert p.majlis == "Zion"


@pytest.mark.asyncio
async def test_validate_signup_profile_precheck_conflict(db):
    a = await _mk_user(db, 1)
    await upsert_profile(db, a.id, MkaProfileIn(majlis="Zion", amc_id="9"))
    with pytest.raises(HTTPException) as e:
        await validate_signup_profile(db, {"majlis": "Zion", "amc_id": "9"}, is_oauth=False)
    assert e.value.status_code == 409


@pytest.mark.asyncio
async def test_save_signup_profile_none_is_noop(db):
    u = await _mk_user(db, 1)
    await save_signup_profile(db, u.id, None)
    assert await get_profile(db, u.id) is None
```

- [ ] **Step 3: Run to verify failure**

Run: `cd apps/api && python -m pytest src/tests/services/test_mka_profile_store.py -v`
Expected: `ModuleNotFoundError: src.db.mka_user_profile`.

- [ ] **Step 4: Write the model**

```python
# apps/api/src/db/mka_user_profile.py
"""MKA fork: one-to-one profile row for Majlis/Region reporting.

Kept in a side table (not columns on `user`) so upstream's User model and
table are never modified. A user without a row has an incomplete profile.
"""

from typing import Optional

from sqlalchemy import Column, ForeignKey, Index, Integer, text
from sqlmodel import Field, SQLModel


class MkaUserProfile(SQLModel, table=True):
    __tablename__ = "mka_user_profile"
    __table_args__ = (
        # Partial on Postgres (NULL AMC IDs never collide). SQLite ignores the
        # dialect-specific clause; NULLs are already distinct there.
        Index(
            "ix_mka_user_profile_amc_id",
            "amc_id",
            unique=True,
            postgresql_where=text("amc_id IS NOT NULL"),
        ),
        Index("ix_mka_user_profile_region", "region"),
        Index("ix_mka_user_profile_majlis", "majlis"),
    )

    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
        )
    )
    majlis: str
    region: str
    mobile: Optional[str] = None
    amc_id: Optional[str] = None
    tanzeem: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
```

- [ ] **Step 5: Write the migration**

```python
# apps/api/migrations/versions/mka_20261004_user_profile.py
"""MKA fork: add mka_user_profile (Majlis/Region reporting)

Revision ID: mka_20261004_user_profile
Revises: b1c2d3e4f5a6
Create Date: 2026-10-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "mka_20261004_user_profile"
down_revision: Union[str, None] = "b1c2d3e4f5a6"  # re-verify with `alembic heads` before merging
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mka_user_profile",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("majlis", sa.String(), nullable=False),
        sa.Column("region", sa.String(), nullable=False),
        sa.Column("mobile", sa.String(), nullable=True),
        sa.Column("amc_id", sa.String(), nullable=True),
        sa.Column("tanzeem", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_mka_user_profile_amc_id", "mka_user_profile", ["amc_id"],
        unique=True, postgresql_where=sa.text("amc_id IS NOT NULL"),
    )
    op.create_index("ix_mka_user_profile_region", "mka_user_profile", ["region"])
    op.create_index("ix_mka_user_profile_majlis", "mka_user_profile", ["majlis"])


def downgrade() -> None:
    op.drop_index("ix_mka_user_profile_majlis", table_name="mka_user_profile")
    op.drop_index("ix_mka_user_profile_region", table_name="mka_user_profile")
    op.drop_index("ix_mka_user_profile_amc_id", table_name="mka_user_profile")
    op.drop_table("mka_user_profile")
```

If Step 1 showed the `user` table is not named `"user"`, change both `ForeignKey` strings accordingly.

- [ ] **Step 6: Append persistence functions to `mka_profile.py`**

Add these imports at the top of the file (merge with existing import block):

```python
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.mka_user_profile import MkaUserProfile
```

Append at the bottom:

```python
_AMC_TAKEN = "That AMC ID is already registered"


async def get_profile(db_session: AsyncSession, user_id: int) -> Optional[MkaUserProfile]:
    stmt = select(MkaUserProfile).where(MkaUserProfile.user_id == user_id)
    return (await db_session.execute(stmt)).scalars().first()


async def profile_status(db_session: AsyncSession, user_id: int) -> dict:
    row = await get_profile(db_session, user_id)
    if row is None:
        return {"complete": False}
    return {
        "complete": True,
        "majlis": row.majlis,
        "region": row.region,
        "mobile": row.mobile,
        "amc_id": row.amc_id,
        "tanzeem": row.tanzeem,
    }


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
    db_session: AsyncSession, user_id: int, data: MkaProfileIn
) -> MkaUserProfile:
    if await _amc_taken(db_session, data.amc_id, exclude_user_id=user_id):
        raise HTTPException(status_code=409, detail=_AMC_TAKEN)
    now = str(datetime.now())
    row = await get_profile(db_session, user_id)
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
        raise HTTPException(status_code=409, detail=_AMC_TAKEN)
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
    db_session: AsyncSession, user_id: int, data: Optional[MkaProfileIn]
) -> None:
    """Run right after the user commit. A failure here leaves the user to the gate."""
    if data is None:
        return
    await upsert_profile(db_session, user_id, data)
```

- [ ] **Step 7: Run to verify pass**

Run: `cd apps/api && python -m pytest src/tests/services/test_mka_profile_store.py src/tests/services/test_mka_profile_domain.py -v`
Expected: all PASS. If the table is missing in SQLite, the model module is not imported before `create_all`; the `from src.db.mka_user_profile import MkaUserProfile` at the top of `mka_profile.py` (and the test's own import) must be present.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/db/mka_user_profile.py apps/api/migrations/versions/mka_20261004_user_profile.py apps/api/src/services/users/mka_profile.py apps/api/src/tests/services/test_mka_profile_store.py
git commit -m "feat(profile): add mka_user_profile table and persistence"
```

---

### Task 3: Signup hooks (the only upstream backend edits)

**Files:**
- Modify: `apps/api/src/db/users.py` (`UserCreate`, one field)
- Modify: `apps/api/src/services/users/users.py` (`create_user`, `create_user_without_org`: imports + 2 hook lines each)
- Test: `apps/api/src/tests/services/test_mka_profile_signup.py`

**Interfaces:**
- Consumes: `validate_signup_profile`, `save_signup_profile` (Task 2).
- Produces: `UserCreate.mka_profile: Optional[dict] = None`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/src/tests/services/test_mka_profile_signup.py
from contextlib import ExitStack
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from sqlmodel import select

from src.db.mka_user_profile import MkaUserProfile
from src.db.users import User, UserCreate
from src.services.users.mka_profile import profile_status
from src.services.users.users import create_user, create_user_without_org


def _signup_patches():
    stack = ExitStack()
    for target, kwargs in [
        ("src.services.users.users.validate_password_complexity", {"return_value": Mock(is_valid=True)}),
        ("src.services.users.users.check_limits_with_usage", {}),
        ("src.services.users.users.increase_feature_usage", {}),
        ("src.services.users.users.track", {"new_callable": AsyncMock}),
        ("src.services.users.users.dispatch_webhooks", {"new_callable": AsyncMock}),
        ("src.services.users.users.send_account_creation_email", {}),
        ("src.services.users.email_verification.send_verification_email", {"new_callable": AsyncMock}),
        ("src.services.users.users.get_deployment_mode", {"return_value": "oss"}),
        ("src.services.users.users.authorization_verify_based_on_roles_and_authorship", {"new_callable": AsyncMock}),
    ]:
        stack.enter_context(patch(target, **kwargs))
    return stack


def _body(name, **extra):
    return UserCreate(
        username=name, first_name="F", last_name="L",
        email=f"{name}@test.com", password="Passw0rd!x", **extra,
    )


async def _user_count(db):
    return len((await db.execute(select(User))).scalars().all())


@pytest.mark.asyncio
async def test_email_signup_stores_profile_and_derives_region(mock_request, db, admin_user, org):
    with _signup_patches():
        created = await create_user(
            mock_request, db, admin_user,
            _body("p1", mka_profile={"majlis": "Baltimore", "region": "Midwest", "amc_id": "42"}),
            org.id,
        )
    s = await profile_status(db, created.id)
    assert (s["majlis"], s["region"], s["amc_id"]) == ("Baltimore", "East", "42")


@pytest.mark.asyncio
async def test_email_signup_without_majlis_is_422_and_creates_no_user(mock_request, db, admin_user, org):
    before = await _user_count(db)
    with _signup_patches(), pytest.raises(HTTPException) as e:
        await create_user(mock_request, db, admin_user, _body("p2"), org.id)
    assert e.value.status_code == 422
    assert await _user_count(db) == before


@pytest.mark.asyncio
async def test_duplicate_amc_at_signup_is_409_and_creates_no_user(mock_request, db, admin_user, org):
    with _signup_patches():
        await create_user(mock_request, db, admin_user,
                          _body("p3", mka_profile={"majlis": "Zion", "amc_id": "5"}), org.id)
    before = await _user_count(db)
    with _signup_patches(), pytest.raises(HTTPException) as e:
        await create_user(mock_request, db, admin_user,
                          _body("p4", mka_profile={"majlis": "Zion", "amc_id": "5"}), org.id)
    assert e.value.status_code == 409
    assert await _user_count(db) == before


@pytest.mark.asyncio
async def test_oauth_signup_without_profile_succeeds_and_is_incomplete(mock_request, db, admin_user, org):
    with _signup_patches():
        created = await create_user(
            mock_request, db, admin_user, _body("g1"), org.id,
            is_oauth=True, signup_provider="google",
        )
    assert await profile_status(db, created.id) == {"complete": False}


@pytest.mark.asyncio
async def test_unknown_keys_in_mka_profile_are_not_stored(mock_request, db, admin_user, org):
    with _signup_patches():
        created = await create_user(
            mock_request, db, admin_user,
            _body("p5", mka_profile={"majlis": "Zion", "extra_metadata": {"x": 1}, "is_superadmin": True}),
            org.id,
        )
    user = (await db.execute(select(User).where(User.id == created.id))).scalars().first()
    assert user.is_superadmin is False
    assert not user.extra_metadata  # None or {} — never the submitted blob


@pytest.mark.asyncio
async def test_org_less_signup_requires_and_stores_profile(mock_request, db, admin_user):
    with _signup_patches():
        with pytest.raises(HTTPException) as e:
            await create_user_without_org(mock_request, db, admin_user, _body("o1"))
        assert e.value.status_code == 422
        created = await create_user_without_org(
            mock_request, db, admin_user, _body("o2", mka_profile={"majlis": "Zion"}),
        )
    assert (await profile_status(db, created.id))["region"] == "Midwest"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && python -m pytest src/tests/services/test_mka_profile_signup.py -v`
Expected: FAIL (`UserCreate` rejects/ignores `mka_profile`; no profile stored).

- [ ] **Step 3: Add the `UserCreate` field** — in `apps/api/src/db/users.py`, directly after the `custom_fields: Optional[dict] = None` line inside `class UserCreate(UserBase):` add exactly:

```python
    # MKA fork: Majlis/Region profile (validated in services/users/mka_profile.py)
    mka_profile: Optional[dict] = None
```

- [ ] **Step 4: Add the imports** — in `apps/api/src/services/users/users.py`, next to the existing `block_non_google_auth` import (find it with `grep -n "mka_google_only" apps/api/src/services/users/users.py`), add:

```python
from src.services.users.mka_profile import save_signup_profile, validate_signup_profile  # MKA fork
```

- [ ] **Step 5: Hook `create_user`** (read the function first; anchors are verbatim lines)

1. Immediately BEFORE the line `    user = User.model_validate(user_object)` (first occurrence, inside `create_user`, after the `_reject_urls_in_profile_fields(...)` call) insert:

```python
    mka_profile = await validate_signup_profile(db_session, user_object.mka_profile, is_oauth)  # MKA fork
```

2. Immediately AFTER the first `await db_session.refresh(user)` that follows `db_session.add(user)` / `await db_session.commit()` in `create_user` (i.e. right before the `# Link user and organization` comment) insert:

```python
    await save_signup_profile(db_session, user.id, mka_profile)  # MKA fork
```

- [ ] **Step 6: Hook `create_user_without_org`** — same two insertions: before its `user = User.model_validate(user_object)` (use `is_oauth`), and after its `await db_session.refresh(user)` that follows `db_session.add(user)` / `commit()` (the one before `user_read = ...`). Use identical lines (with `# MKA fork`). Do **not** hook `create_user_with_invite` (it delegates to `create_user`).

- [ ] **Step 7: Run to verify pass, plus regressions**

Run:
```bash
cd apps/api && python -m pytest src/tests/services/test_mka_profile_signup.py src/tests/services/test_signup_custom_fields_flow.py src/tests/services/test_users_service.py -v
```
Expected: new tests PASS. **Existing** signup tests that call `create_user` without `mka_profile` and `is_oauth=False` will now fail with 422 — that is the intended new rule. Update those existing tests minimally by adding `mka_profile={"majlis": "Zion"}` to their `UserCreate(...)` calls (or `is_oauth=True` where the test is about OAuth). List every test you touched in the commit body. If more than ~10 existing tests need changes, stop and report to the coordinator instead of continuing.

- [ ] **Step 8: Full API suite smoke**

Run: `cd apps/api && python -m pytest src/tests -x -q`
Expected: PASS (or only failures that also fail on a clean checkout of `dev`; report those).

- [ ] **Step 9: Commit**

```bash
git add apps/api/src/db/users.py apps/api/src/services/users/users.py apps/api/src/tests
git commit -m "feat(profile): require Majlis on signup via fork hooks"
```

---

### Task 4: Fork-only router (`/mka/profile`) and registration

**Files:**
- Create: `apps/api/src/routers/mka_profile.py`
- Modify: `apps/api/src/router.py` (one `include_router` block + import)
- Test: `apps/api/src/tests/routers/test_mka_profile_router.py`

**Interfaces:**
- Consumes: `options_payload`, `profile_status`, `upsert_profile`, `MkaProfileIn` (Tasks 1–2); `get_authenticated_user` (`src.security.auth`), `get_db_session` (`src.core.events.database`), `is_org_admin`, `is_user_superadmin` (`src.security.org_auth`), `UserOrganization` (`src.db.user_organizations`).
- Produces (HTTP, mounted under `/api/v1`): `GET /mka/profile/options`, `GET /mka/profile/me`, `PUT /mka/profile/me`, `PUT /mka/profile/user/{user_id}?org_id=`.

- [ ] **Step 1: Write the failing tests** (handlers are plain async functions; call them directly)

```python
# apps/api/src/tests/routers/test_mka_profile_router.py
import pytest
from fastapi import HTTPException

from src.routers import mka_profile as r
from src.services.users.mka_profile import MkaProfileIn, profile_status


@pytest.mark.asyncio
async def test_options_endpoint():
    o = await r.api_options()
    assert len(o["majlis"]) == 52


@pytest.mark.asyncio
async def test_me_get_then_put(db, regular_user):
    assert await r.api_get_me(current_user=regular_user, db_session=db) == {"complete": False}
    out = await r.api_put_me(
        body=MkaProfileIn(majlis="Seattle", tanzeem="khadim"),
        current_user=regular_user, db_session=db,
    )
    assert out["region"] == "Northwest" and out["complete"] is True
    assert (await profile_status(db, regular_user.id))["majlis"] == "Seattle"


@pytest.mark.asyncio
async def test_admin_can_edit_member_in_their_org(db, org, admin_user, regular_user):
    out = await r.api_put_user(
        user_id=regular_user.id, org_id=org.id,
        body=MkaProfileIn(majlis="Zion"),
        current_user=admin_user, db_session=db,
    )
    assert out["region"] == "Midwest"


@pytest.mark.asyncio
async def test_regular_user_cannot_edit_others(db, org, admin_user, regular_user):
    with pytest.raises(HTTPException) as e:
        await r.api_put_user(
            user_id=admin_user.id, org_id=org.id,
            body=MkaProfileIn(majlis="Zion"),
            current_user=regular_user, db_session=db,
        )
    assert e.value.status_code == 403
    assert (await profile_status(db, admin_user.id)) == {"complete": False}


@pytest.mark.asyncio
async def test_admin_cannot_edit_user_outside_their_org(db, org, other_org, admin_user):
    from datetime import datetime
    from src.db.users import User
    outsider = User(
        username="out", first_name="O", last_name="U", email="out@test.com",
        password="x", user_uuid="user_out",
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )
    db.add(outsider)
    await db.commit()
    await db.refresh(outsider)
    with pytest.raises(HTTPException) as e:
        await r.api_put_user(
            user_id=outsider.id, org_id=org.id,
            body=MkaProfileIn(majlis="Zion"),
            current_user=admin_user, db_session=db,
        )
    assert e.value.status_code == 404


def test_router_is_registered():
    from src.router import v1_router
    paths = {getattr(rt, "path", "") for rt in v1_router.routes}
    assert "/mka/profile/options" in paths
    assert "/mka/profile/me" in paths
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && python -m pytest src/tests/routers/test_mka_profile_router.py -v`
Expected: `ModuleNotFoundError: src.routers.mka_profile`.

- [ ] **Step 3: Write the router**

```python
# apps/api/src/routers/mka_profile.py
"""MKA fork: Majlis/Region profile endpoints (mounted at /mka/profile)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.user_organizations import UserOrganization
from src.security.auth import get_authenticated_user
from src.security.org_auth import is_org_admin, is_user_superadmin
from src.services.users.mka_profile import (
    MkaProfileIn,
    options_payload,
    profile_status,
    upsert_profile,
)

router = APIRouter()


def _uid(current_user) -> int:
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
    """Org admins edit members of their org; superadmins may edit anyone."""
    caller = _uid(current_user)
    superadmin = await is_user_superadmin(caller, db_session)
    if not superadmin:
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
```

- [ ] **Step 4: Register it** — in `apps/api/src/router.py`:
1. Add `from src.routers import mka_profile as mka_profile_router_module  # MKA fork` with the other `from src.routers import …` lines at the top.
2. Directly after the closing `)` of the `v1_router.include_router(users.router, …)` block, add:

```python
v1_router.include_router(  # MKA fork
    mka_profile_router_module.router,
    prefix="/mka/profile",
    tags=["mka-profile"],
    dependencies=[Depends(get_non_api_token_user)],
)
```

`/options` is public because `get_non_api_token_user` admits anonymous callers (same as `/users`).

- [ ] **Step 5: Run to verify pass**

Run: `cd apps/api && python -m pytest src/tests/routers/test_mka_profile_router.py -v && python -m pytest src/tests -x -q`
Expected: PASS. If `is_user_superadmin` is not importable from `src.security.org_auth`, `grep -rn "def is_user_superadmin" apps/api/src` and import from where it is defined.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/routers/mka_profile.py apps/api/src/router.py apps/api/src/tests/routers/test_mka_profile_router.py
git commit -m "feat(profile): add /mka/profile router"
```

---

### Task 5: Frontend foundations — shadcn `command`, API client, validation, Majlis combobox, fields component

**Files:**
- Create (via CLI): `apps/web/components/ui/command.tsx`
- Create: `apps/web/services/mka/profile.ts`
- Create: `apps/web/components/mka/MajlisCombobox.tsx`
- Create: `apps/web/components/mka/MkaProfileFields.tsx`

**Interfaces:**
- Produces:
  - `services/mka/profile.ts`: types `MkaProfileValues`, `MkaOptions`, `MkaProfileStatus`; `class MkaProfileError`; `getMkaOptions()`, `getMyMkaProfile(token)`, `putMyMkaProfile(values, token)`, `emptyMkaProfile`, `validateMkaProfile(values)`, `mkaValuesToBody(values)`
  - `MajlisCombobox` props `{ value: string; onChange(name: string): void; options: MkaOptions['majlis']; id?: string; invalid?: boolean; disabled?: boolean }`
  - `MkaProfileFields` props `{ values: MkaProfileValues; errors?: Partial<Record<keyof MkaProfileValues, string>>; onChange(field: keyof MkaProfileValues, value: string): void; disabled?: boolean; idPrefix?: string }`

- [ ] **Step 1: Install the shadcn command component** (never `--overwrite`)

```bash
cd apps/web && bunx --bun shadcn@latest add command
```
If prompted to overwrite `dialog.tsx`, `button.tsx`, `input.tsx` or `popover.tsx`, answer **No**. If it proposes a `globals.css` change, answer **No**. Then:
```bash
git status --short apps/web
```
Expected: exactly one new file `apps/web/components/ui/command.tsx` (plus possibly `bun.lock`/`package.json` if it added a dependency — `cmdk` is already present, so none expected). Read the generated file; it must use theme tokens (`bg-popover`, `text-popover-foreground`, `text-muted-foreground`, `bg-accent`) and import `@/components/ui/dialog` and `cmdk`. If it created/changed any other file, `git checkout` those and report.

- [ ] **Step 2: Study the neighbors (read-only)** — open `apps/web/components/ui/select.tsx` (export names), `apps/web/components/ui/input.tsx`, `apps/web/components/ui/label.tsx`, and `apps/web/components/Auth/CompleteSignupFields.tsx` (to copy its exact `useQuery` import path — `@tanstack/react-query` vs `react-query` — and `useLHSession` import path). Use those exact import paths in all new files below.

- [ ] **Step 3: Write the client and validation**

```ts
// apps/web/services/mka/profile.ts
import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader } from '@services/utils/ts/requests'

export type MkaProfileValues = {
  majlis: string
  mobile: string
  amc_id: string
  tanzeem: string
}

export type MkaOptions = {
  majlis: { name: string; region: string }[]
  tanzeem: { value: string; label: string }[]
}

export type MkaProfileStatus =
  | { complete: false }
  | {
      complete: true
      majlis: string
      region: string
      mobile: string | null
      amc_id: string | null
      tanzeem: string | null
    }

export const emptyMkaProfile: MkaProfileValues = {
  majlis: '',
  mobile: '',
  amc_id: '',
  tanzeem: '',
}

export class MkaProfileError extends Error {
  status: number
  fields: Partial<Record<keyof MkaProfileValues, string>>
  constructor(status: number, message: string, fields = {}) {
    super(message)
    this.status = status
    this.fields = fields
  }
}

const US_MOBILE = /^(?:\+?1)?([2-9]\d{2})([2-9]\d{2})(\d{4})$/

export function validateMkaProfile(
  v: MkaProfileValues
): Partial<Record<keyof MkaProfileValues, string>> {
  const errors: Partial<Record<keyof MkaProfileValues, string>> = {}
  if (!v.majlis.trim()) errors.majlis = 'Majlis is required'
  const mobile = v.mobile.trim()
  if (mobile) {
    if (/[A-Za-z]/.test(mobile) || !US_MOBILE.test(mobile.replace(/[\s().-]/g, ''))) {
      errors.mobile = 'Enter a valid US mobile number'
    }
  }
  const amc = v.amc_id.trim()
  if (amc && !/^[0-9]{1,15}$/.test(amc)) errors.amc_id = 'AMC ID must contain digits only'
  return errors
}

/** Body for the API: empty optional strings become null. Never includes region. */
export function mkaValuesToBody(v: MkaProfileValues) {
  return {
    majlis: v.majlis.trim(),
    mobile: v.mobile.trim() || null,
    amc_id: v.amc_id.trim() || null,
    tanzeem: v.tanzeem.trim() || null,
  }
}

async function parseError(res: Response): Promise<MkaProfileError> {
  let detail: unknown = null
  try {
    detail = (await res.json())?.detail
  } catch {
    /* non-JSON body */
  }
  const fields: Partial<Record<keyof MkaProfileValues, string>> = {}
  let message = 'Something went wrong. Please try again.'
  if (typeof detail === 'string') {
    message = detail
    if (res.status === 409) fields.amc_id = detail
  } else if (Array.isArray(detail)) {
    for (const d of detail) {
      // our own {field, message} items, or FastAPI's {loc, msg}
      const field = (d.field ?? (Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : '')) as
        | keyof MkaProfileValues
        | ''
      const msg = String(d.message ?? d.msg ?? '').replace(/^Value error, /, '')
      if (field && msg) fields[field] = msg
    }
    message = Object.values(fields)[0] ?? message
  }
  return new MkaProfileError(res.status, message, fields)
}

export async function getMkaOptions(): Promise<MkaOptions> {
  const res = await fetch(`${getAPIUrl()}mka/profile/options`)
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export async function getMyMkaProfile(token: string): Promise<MkaProfileStatus> {
  const res = await fetch(
    `${getAPIUrl()}mka/profile/me`,
    RequestBodyWithAuthHeader('GET', null, null, token)
  )
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export async function putMyMkaProfile(
  values: MkaProfileValues,
  token: string
): Promise<MkaProfileStatus> {
  const res = await fetch(
    `${getAPIUrl()}mka/profile/me`,
    RequestBodyWithAuthHeader('PUT', mkaValuesToBody(values), null, token)
  )
  if (!res.ok) throw await parseError(res)
  return res.json()
}
```

- [ ] **Step 5: Write the combobox** (shadcn Combobox pattern: `Popover` + `Command`; no custom primitive)

```tsx
// apps/web/components/mka/MajlisCombobox.tsx
'use client'

import * as React from 'react'
import { Check, ChevronsUpDown } from 'lucide-react'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { MkaOptions } from '@services/mka/profile'

type Props = {
  value: string
  onChange: (name: string) => void
  options: MkaOptions['majlis']
  id?: string
  invalid?: boolean
  disabled?: boolean
}

export default function MajlisCombobox({ value, onChange, options, id, invalid, disabled }: Props) {
  const [open, setOpen] = React.useState(false)

  const groups = React.useMemo(() => {
    const byRegion = new Map<string, MkaOptions['majlis']>()
    for (const o of options) {
      byRegion.set(o.region, [...(byRegion.get(o.region) ?? []), o])
    }
    return Array.from(byRegion.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [options])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-invalid={invalid || undefined}
          disabled={disabled}
          className={cn(
            'w-full justify-between font-normal',
            !value && 'text-muted-foreground',
            invalid && 'border-destructive'
          )}
        >
          {value || 'Select your Majlis'}
          <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) p-0" align="start">
        <Command>
          <CommandInput placeholder="Search Majlis or Region…" />
          <CommandList>
            <CommandEmpty>No Majlis found.</CommandEmpty>
            {groups.map(([region, items]) => (
              <CommandGroup key={region} heading={region}>
                {items.map((m) => (
                  <CommandItem
                    key={m.name}
                    value={`${m.name} ${m.region}`}
                    onSelect={() => {
                      onChange(m.name)
                      setOpen(false)
                    }}
                  >
                    <Check className={cn('mr-2 size-4', value === m.name ? 'opacity-100' : 'opacity-0')} />
                    {m.name}
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
```
If `Button` has no `variant="outline"`, open `ui/button.tsx` and use its closest outlined variant name. If `lucide-react` v1 lacks `ChevronsUpDown`/`Check` names, check the icons already imported by `components/ui/select.tsx` and use the same ones.

- [ ] **Step 6: Write the fields component**

```tsx
// apps/web/components/mka/MkaProfileFields.tsx
'use client'

import { useQuery } from '@tanstack/react-query' // use the exact import path found in Step 2
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import MajlisCombobox from './MajlisCombobox'
import { getMkaOptions, type MkaProfileValues } from '@services/mka/profile'

type Props = {
  values: MkaProfileValues
  errors?: Partial<Record<keyof MkaProfileValues, string>>
  onChange: (field: keyof MkaProfileValues, value: string) => void
  disabled?: boolean
  idPrefix?: string
}

const NONE = '__none__' // Radix Select forbids empty-string item values

export default function MkaProfileFields({
  values,
  errors = {},
  onChange,
  disabled,
  idPrefix = 'mka',
}: Props) {
  const { data: options, isError } = useQuery({
    queryKey: ['mka-profile-options'],
    queryFn: getMkaOptions,
    staleTime: Infinity,
  })
  const region = options?.majlis.find((m) => m.name === values.majlis)?.region

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-majlis`}>Majlis *</Label>
        <MajlisCombobox
          id={`${idPrefix}-majlis`}
          value={values.majlis}
          onChange={(v) => onChange('majlis', v)}
          options={options?.majlis ?? []}
          invalid={!!errors.majlis}
          disabled={disabled || !options}
        />
        {region && <p className="text-xs text-muted-foreground">Region: {region}</p>}
        {isError && (
          <p className="text-xs text-destructive">Couldn&apos;t load Majlis list. Refresh to retry.</p>
        )}
        {errors.majlis && <p className="text-xs text-destructive">{errors.majlis}</p>}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-mobile`}>Mobile number (optional)</Label>
        <Input
          id={`${idPrefix}-mobile`}
          type="tel"
          inputMode="tel"
          autoComplete="tel-national"
          placeholder="(555) 234-0142"
          value={values.mobile}
          disabled={disabled}
          aria-invalid={!!errors.mobile || undefined}
          onChange={(e) => onChange('mobile', e.target.value)}
        />
        {errors.mobile && <p className="text-xs text-destructive">{errors.mobile}</p>}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-amc`}>AMC ID (optional)</Label>
        <Input
          id={`${idPrefix}-amc`}
          inputMode="numeric"
          autoComplete="off"
          placeholder="Digits only"
          value={values.amc_id}
          disabled={disabled}
          aria-invalid={!!errors.amc_id || undefined}
          onChange={(e) => onChange('amc_id', e.target.value)}
        />
        {errors.amc_id && <p className="text-xs text-destructive">{errors.amc_id}</p>}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-tanzeem`}>Tanzeem (optional)</Label>
        <Select
          value={values.tanzeem || NONE}
          onValueChange={(v) => onChange('tanzeem', v === NONE ? '' : v)}
          disabled={disabled}
        >
          <SelectTrigger id={`${idPrefix}-tanzeem`} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>Not specified</SelectItem>
            {(options?.tanzeem ?? []).map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {errors.tanzeem && <p className="text-xs text-destructive">{errors.tanzeem}</p>}
      </div>
    </div>
  )
}
```

- [ ] **Step 7: Verify**

```bash
cd apps/web && bunx tsc --noEmit 2>&1 | grep -E "components/mka|services/mka|components/ui/command" ; bun run lint:strict 2>&1 | grep -E "components/mka|services/mka|components/ui/command" ; echo "lint/tsc scan done"
```
Expected: no output lines before `lint/tsc scan done` (no errors in the new files). Fix any reported, but only within these four files.

- [ ] **Step 8: Commit**

```bash
git add apps/web/components/ui/command.tsx apps/web/services/mka apps/web/components/mka apps/web/package.json apps/web/bun.lock 2>/dev/null
git commit -m "feat(profile): add Majlis combobox and MKA profile fields (shadcn command)"
```
(`git add` of unchanged `package.json`/`bun.lock` is harmless; do not stage anything else.)

---

### Task 6: Signup forms and Next signup route

**Files:**
- Modify: `apps/web/app/api/signup/route.ts` (upstream; hook)
- Modify: `apps/web/app/auth/signup/OpenSignup.tsx` (upstream; hook)
- Modify: `apps/web/app/auth/signup/InviteOnlySignUp.tsx` (upstream; hook)

**Interfaces:**
- Consumes: `MkaProfileFields`, `emptyMkaProfile`, `validateMkaProfile`, `MkaProfileValues` (Task 5).
- Produces: signup request body includes `mka_profile: {majlis, mobile, amc_id, tanzeem}`; route forwards only those four keys.

- [ ] **Step 1: Read the three files fully** (`route.ts` lines 1–140; `OpenSignup.tsx` lines 40–140 and the JSX around line 373; the same regions of `InviteOnlySignUp.tsx`). Find: (a) where the route destructures the request body (the place `custom_fields` comes from), (b) the Formik `initialValues` and the validate function that sets `errors.custom_fields`, (c) the JSX line `<CustomSignupFields fields={customFields} formik={formik} />`, (d) the submit code that sends values to `/api/signup`. Confirm whether the whole `values` object is posted (so `mka_profile` rides along automatically) or fields are listed explicitly.

- [ ] **Step 2: Route hook** — in `route.ts`, add `mka_profile` to the destructure that yields `custom_fields`, and in `backendBody` add, directly after the `...(custom_fields ? { custom_fields } : {}),` line:

```ts
    // MKA fork: forward only the four known profile keys (never spread client input)
    ...(mka_profile && typeof mka_profile === 'object'
      ? {
          mka_profile: {
            majlis: mka_profile.majlis,
            mobile: mka_profile.mobile,
            amc_id: mka_profile.amc_id,
            tanzeem: mka_profile.tanzeem,
          },
        }
      : {}),
```
Add `// MKA fork` on the destructure change. Ensure the TS types accept `mka_profile` (type it `any`-free: `mka_profile?: { majlis?: string; mobile?: string | null; amc_id?: string | null; tanzeem?: string | null }` if the body is typed).

- [ ] **Step 3: `OpenSignup.tsx` hooks** (all marked `// MKA fork`):
1. Imports: `import MkaProfileFields from '@components/mka/MkaProfileFields'` and `import { emptyMkaProfile, validateMkaProfile, mkaValuesToBody } from '@services/mka/profile'`. (If the `@components` alias doesn't resolve `components/mka`, use the relative alias style the file already uses.)
2. `initialValues`: add `mka_profile: { ...emptyMkaProfile },` next to `custom_fields: initialCustomFieldValues(customFields),`.
3. In the validate function, directly after the `customFieldErrors` block, add:
```ts
  // MKA fork
  const mkaErrors = validateMkaProfile(values.mka_profile)
  if (Object.keys(mkaErrors).length) errors.mka_profile = mkaErrors
```
(If `errors` is typed, widen its type minimally to allow `mka_profile`.)
4. JSX: directly after `<CustomSignupFields fields={customFields} formik={formik} />` add:
```tsx
          {/* MKA fork */}
          <MkaProfileFields
            idPrefix="signup"
            values={formik.values.mka_profile}
            errors={(formik.touched.mka_profile || formik.submitCount > 0 ? formik.errors.mka_profile : undefined) as any}
            onChange={(field, value) => {
              formik.setFieldValue(`mka_profile.${field}`, value)
              formik.setFieldTouched('mka_profile', true, false)
            }}
          />
```
Replace `as any` with a proper cast to `Partial<Record<keyof MkaProfileValues, string>>` (import the type) — do not leave `any`.
5. Submit: if the submit code posts the whole `values`, ensure `mka_profile` is sent as `mkaValuesToBody(values.mka_profile)` (so empty optionals become null). If it builds an explicit object, add `mka_profile: mkaValuesToBody(values.mka_profile)` beside `custom_fields`.
6. Server errors: where the submit handler maps API errors to the form, add handling so a 409 AMC conflict or 422 field error from `/api/signup` shows on the matching `mka_profile.*` field (the route returns the backend `detail` verbatim; reuse the same status/detail the handler already reads). If the handler only shows a generic toast, ensure the toast text contains the API message (e.g., "That AMC ID is already registered").

- [ ] **Step 4: `InviteOnlySignUp.tsx`** — apply Step 3's six changes identically.

- [ ] **Step 5: Verify**

```bash
cd apps/web && bunx tsc --noEmit 2>&1 | grep -E "signup|mka" ; bun run lint:strict 2>&1 | grep -E "signup|mka"; echo scan done
```
Expected: nothing before `scan done`. Then run the dev server (`bun run dev` in `apps/web`, API running per README) and manually: open the signup page in light and dark mode; submit with no Majlis (field error, no request sent); pick a Majlis (Region line appears); enter `12a` as AMC ID (error); submit valid → account created; confirm in DB: `select * from mka_user_profile;` has the row with the derived region. Record what you actually saw; if you cannot run the stack, say so explicitly rather than claiming it works.

- [ ] **Step 6: Commit**

```bash
git add apps/web/app/api/signup/route.ts apps/web/app/auth/signup/OpenSignup.tsx apps/web/app/auth/signup/InviteOnlySignUp.tsx
git commit -m "feat(profile): collect Majlis and profile fields at signup"
```

---

### Task 7: Hard profile gate and mount in org layout

**Files:**
- Create: `apps/web/components/mka/MkaProfileGate.tsx`
- Modify: `apps/web/app/orgs/[orgslug]/layout.tsx` (upstream; 2 lines)

**Interfaces:**
- Consumes: `getMyMkaProfile`, `putMyMkaProfile`, `validateMkaProfile`, `emptyMkaProfile`, `MkaProfileError` (Task 5); `MkaProfileFields`.

- [ ] **Step 1: Check three facts (read-only), and record answers in your report**
  - `apps/web/components/ui/dialog.tsx`: how the close X is rendered (`DialogPrimitive.Close` as the last child inside `DialogContent`, around line 73) and which selector hides it without editing the file (expected: `className="[&>button:last-child]:hidden"` or `[&>button[data-slot=dialog-close]]:hidden`).
  - `apps/web/styles/globals.css`: the `--z-popover` and `--z-dialog` (or equivalent overlay/content) values. The Majlis `PopoverContent` is portaled to `body` with `zIndex: var(--z-popover)`; if the Dialog's z-index is **higher**, the list would render behind the gate. If so, pass `style={{ zIndex: 'calc(var(--z-dialog) + 10)' }}` (or the correct variable) to the `PopoverContent` inside `MajlisCombobox` via a new optional `contentStyle`/`className` prop — do not edit `popover.tsx`.
  - How sign-out is done elsewhere: `grep -rn "signOut" apps/web --include=*.tsx | head` and reuse that exact function/import.

- [ ] **Step 2: Write the gate**

```tsx
// apps/web/components/mka/MkaProfileGate.tsx
'use client'

import { useFormik } from 'formik'
import { usePathname } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query' // exact path as in CompleteSignupFields.tsx
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import MkaProfileFields from './MkaProfileFields'
import {
  emptyMkaProfile,
  getMyMkaProfile,
  MkaProfileError,
  putMyMkaProfile,
  validateMkaProfile,
  type MkaProfileValues,
} from '@services/mka/profile'
// sign-out: import the same helper other components use (Step 1), e.g.
// import { signOut } from 'next-auth/react'

export default function MkaProfileGate() {
  const session = useLHSession() as any
  const pathname = usePathname()
  const queryClient = useQueryClient()
  const token: string | undefined = session?.data?.tokens?.access_token

  const { data } = useQuery({
    queryKey: ['mka-profile-me', token],
    queryFn: () => getMyMkaProfile(token as string),
    enabled: !!token,
    staleTime: 60_000,
  })

  const formik = useFormik<{ profile: MkaProfileValues; submitError: string }>({
    initialValues: { profile: { ...emptyMkaProfile }, submitError: '' },
    validate: (v) => {
      const errs = validateMkaProfile(v.profile)
      return Object.keys(errs).length ? ({ profile: errs } as any) : {}
    },
    onSubmit: async (v, { setFieldError, setFieldValue }) => {
      try {
        await putMyMkaProfile(v.profile, token as string)
        await queryClient.invalidateQueries({ queryKey: ['mka-profile-me'] })
      } catch (e) {
        if (e instanceof MkaProfileError) {
          for (const [k, msg] of Object.entries(e.fields)) setFieldError(`profile.${k}`, msg)
          setFieldValue('submitError', Object.keys(e.fields).length ? '' : e.message, false)
        } else {
          setFieldValue('submitError', 'Something went wrong. Please try again.', false)
        }
      }
    },
  })

  if (!token || pathname?.startsWith('/auth') || !data || data.complete) return null

  const errors = (formik.errors.profile ?? {}) as Partial<Record<keyof MkaProfileValues, string>>

  return (
    <Dialog open>
      <DialogContent
        className="[&>button:last-child]:hidden sm:max-w-md"
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
        onPointerDownOutside={(e) => e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>Complete your profile</DialogTitle>
          <DialogDescription>
            Tell us your Majlis so we can place you in the right Region. This takes a few seconds.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={formik.handleSubmit} className="space-y-4" noValidate>
          <MkaProfileFields
            idPrefix="gate"
            values={formik.values.profile}
            errors={formik.submitCount > 0 ? errors : {}}
            disabled={formik.isSubmitting}
            onChange={(field, value) => formik.setFieldValue(`profile.${field}`, value)}
          />
          {formik.values.submitError && (
            <p className="text-sm text-destructive" role="alert">
              {formik.values.submitError}
            </p>
          )}
          <div className="flex items-center justify-between gap-2">
            <Button type="button" variant="ghost" onClick={() => signOut()}>
              Sign out
            </Button>
            <Button type="submit" disabled={formik.isSubmitting}>
              {formik.isSubmitting ? 'Saving…' : 'Save and continue'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
```
Resolve the `signOut` import per Step 1. Remove the `as any` casts by typing `session` with the context's real type (read `LHSessionContext.tsx`) and typing the Formik error shape; no `any` may remain.

- [ ] **Step 3: Mount it** — in `apps/web/app/orgs/[orgslug]/layout.tsx` add the import `import MkaProfileGate from '@components/mka/MkaProfileGate' // MKA fork` and, directly BEFORE `<CompleteSignupFields />`, add `<MkaProfileGate /> {/* MKA fork */}` (so the blocking gate precedes the legacy dialog). Confirm both render inside `OrgProvider` and that the react-query provider wraps this subtree (it does for `CompleteSignupFields`, which uses react-query).

- [ ] **Step 4: Verify (manual, required)**
  1. `bunx tsc --noEmit` and `bun run lint:strict` show no errors in `mka/` or the layout.
  2. With a user that has no `mka_user_profile` row (any pre-existing account, or a fresh Google-created one): load an org page → gate appears; Esc, outside click and the (hidden) X cannot close it; Tab stays inside; open the Majlis list and confirm it renders **above** the dialog and is searchable (type "sil" → Silicon Valley); pick a Majlis, save → gate disappears without reload and does not return on refresh.
  3. Enter an AMC ID that another user has → "That AMC ID is already registered" under the field; gate stays.
  4. "Sign out" works.
  5. Light and dark mode: gate, combobox list, inputs use theme colors (no white boxes in dark mode). If org branding changes theme variables, check one org with custom branding if available.
  Record exactly what you observed; mark anything you could not test.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/mka/MkaProfileGate.tsx 'apps/web/app/orgs/[orgslug]/layout.tsx' apps/web/components/mka/MajlisCombobox.tsx
git commit -m "feat(profile): add non-dismissible Majlis profile gate"
```

---

### Task 8: Fork bookkeeping, spec sync, final verification

**Files:**
- Modify: `.codebase-memory/upstream-modifications.md`
- Modify: `docs/superpowers/specs/2026-10-04-mka-profile-fields-design.md` (apply the three "Spec corrections" from the top of this plan)

- [ ] **Step 1: Log every upstream-file edit.** Read `.codebase-memory/upstream-modifications.md` and append entries in its existing format (date, file, reason, why no extension point exists, exact diff) for: `apps/api/src/db/users.py` (UserCreate field), `apps/api/src/services/users/users.py` (import + 2 hooks in `create_user`, 2 in `create_user_without_org`), `apps/api/src/router.py` (import + include), `apps/web/app/api/signup/route.ts`, `OpenSignup.tsx`, `InviteOnlySignUp.tsx`, `apps/web/app/orgs/[orgslug]/layout.tsx`. Add one "added file (no upstream conflict today)" entry for `apps/web/components/ui/command.tsx` and a note listing fork-only files (`mka_profile.py`, `mka_user_profile.py`, `routers/mka_profile.py`, migration, `components/mka/*`, `services/mka/profile.ts`, tests). Generate the diffs with `git diff <base>..HEAD -- <file>`; paste verbatim.

- [ ] **Step 2: Sync the spec** with the three corrections (transaction wording in §7/§2, remove the hub-layout row from the §4 hook table, hooks list for create functions). Add a short "Upstream sync checklist" under §4: after `git merge upstream/main` run `grep -rn "MKA fork" apps` and confirm every logged hook is still present, run `alembic heads` (add a merge migration if >1), run `python -m pytest src/tests -q` in `apps/api`, and `bunx shadcn@latest diff command` if upstream adds its own `command.tsx`.

- [ ] **Step 3: Final verification** (report real output):
```bash
cd apps/api && python -m pytest src/tests -q
cd ../web && bunx tsc --noEmit && bun run lint:strict && bun test tests
```
Expected: no new failures vs. a clean `dev` checkout. Compare against baseline by stashing nothing — if failures exist, run the same command on `git stash`-free clean `origin/dev` in a worktree to prove they are pre-existing, and list them.

- [ ] **Step 4: Re-index the codebase graph** per project CLAUDE.md after merge/PR: `mcp__codebase-memory-mcp__index_repository(repo_path="/Users/mamjed/Documents/GitHub/mka-learnhouse", mode="full", persistence=true)` (coordinator does this, not the executor).

- [ ] **Step 5: Commit**

```bash
git add .codebase-memory/upstream-modifications.md docs/superpowers/specs/2026-10-04-mka-profile-fields-design.md
git commit -m "docs(profile): log upstream hooks and sync spec"
```

---

## Self-review (done at plan-writing time)
- **Spec coverage:** fields/validation (T1), side table + AMC uniqueness + migration (T2), signup email/invite/org-less/Google rules (T3), API + admin edit + superadmin (T4), shadcn command combobox / theming rules / Tanzeem select (T5), signup UI (T6), hard gate + sign-out + z-index (T7), fork logging + sync routine + spec corrections (T8). Reporting UI is sub-project 2 (out of scope). Backfill script and API-wide enforcement remain out of scope per spec.
- **Placeholders:** none. The only "read then insert" steps are upstream hook sites whose line numbers drift; each gives verbatim anchor text and the exact code to insert.
- **Type consistency:** `MkaProfileIn`, `parse_profile`, `validate_signup_profile`, `save_signup_profile`, `upsert_profile`, `profile_status`, `options_payload` names match across T1–T4; frontend `MkaProfileValues`/`validateMkaProfile`/`mkaValuesToBody` match across T5–T7.
- **Known unverified assumptions (executors must confirm and report):** `user` table name; `is_user_superadmin` import location; `Button variant="outline"`; lucide v1 icon names; `useQuery` import path; dialog close-button selector; dialog vs popover z-index; whether the signup forms post `values` wholesale.
