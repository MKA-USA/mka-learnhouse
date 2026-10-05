"""MKA fork: cross-module identity-proof sequence (attributes proof x compliance matching).

A user proven for ``a@`` who changes the profile email to a roster role address must NOT be matched to that
address's expected row, before or after any attribute refresh (login hook, admin recompute / override, backfill).
Control: a user who genuinely signs in with Google as the role address (matching ``hd``) IS matched.
Synthetic ``*.invalid`` data only."""

import pytest
from src.db.users import User
from src.services.mka import attributes as attrs
from src.tests.routers.mka_compliance_world import add_user, expected
from src.tests.routers.test_mka_compliance_router import (  # noqa: F401  (fixtures + helpers)
    BASE, client_for, freeze_today, q, world,
)

ATFAL = "role@atfalusa.org"
# (proven address, role address on the roster). The mkausa pair is a REAL officeholder-shaped address; the other
# is a plain domain. Google-only config is cleared so that ONLY the per-login hd can prove ownership.
PAIRS = [
    ("a@proof.example.invalid", "role@proof.example.invalid"),
    ("a.person@mkausa.org", "tabligh.albany@mkausa.org"),
]


@pytest.fixture(autouse=True)
def _no_google_only(monkeypatch):
    monkeypatch.setenv("MKA_GOOGLE_ONLY_DOMAINS", "")


async def _seed_roster(db, org, world, *emails):
    for email in emails:
        db.add(expected(org.id, world.cycle.id, email, "tabligh", "national", None, None, "Role", email.split("@")[0]))
    await db.commit()


async def _totals(db, org):
    async with client_for(db, 1) as c:
        return (await c.get(f"{BASE}/overview", params=q(org))).json()["totals"]


async def _roster_item(db, org, email):
    async with client_for(db, 1) as c:
        items = (await c.get(f"{BASE}/courses/course_tabligh/learners", params=q(org, page_size=200))).json()["items"]
    rows = [i for i in items if (i.get("email") or "").lower() == email.lower()]
    assert len(rows) == 1, rows
    return rows[0]


async def _signed_in(db, org, email):
    r = await _roster_item(db, org, email)
    return r["signed_in"], r["stage"]


def _unrecognised(eff):
    return not eff["is_officeholder"] and eff["status"] in ("unrecognized", "not_applicable")


async def _login(db, user_id, hd):
    """What the Google login hook does: derive with the verified hd of this very login."""
    u = await db.get(User, user_id)
    await attrs.refresh_attributes(db, u, proof_hd=hd)
    await db.commit()


async def _change_email(db, user_id, new):
    u = await db.get(User, user_id)
    u.email = new
    db.add(u)
    await db.commit()
    return u


@pytest.mark.asyncio
@pytest.mark.parametrize("a_email,role_email", PAIRS)
async def test_email_change_to_a_role_address_never_matches_the_role_row(db, org, world, a_email, role_email):
    domain = a_email.split("@")[1]
    await _seed_roster(db, org, world, a_email, role_email)
    await add_user(db, org.id, 50, a_email, 4, signup="google")
    await _login(db, 50, domain)                                   # proven for a@ (Google login, matching hd)
    assert (await _signed_in(db, org, a_email))[0] is True
    assert (await _signed_in(db, org, role_email))[0] is False
    base = await _totals(db, org)

    u = await _change_email(db, 50, role_email)                    # profile email -> role address
    # (a) before any refresh: stale row, fail closed
    assert await _signed_in(db, org, role_email) == (False, "not_signed_in")
    assert _unrecognised((await attrs.read_effective(db, u))[0])
    assert (await _totals(db, org))["not_signed_in"] == base["not_signed_in"] + 1  # a@ is no longer matched either
    assert (await _totals(db, org))["expected"] == base["expected"]

    # (b1) admin recompute / backfill
    await attrs.recompute_users(db, org_id=org.id)
    await db.commit()
    u = await db.get(User, 50)
    assert await _signed_in(db, org, role_email) == (False, "not_signed_in")
    assert _unrecognised((await attrs.read_effective(db, u))[0])
    row = await attrs.get_row(db, 50)
    assert row.verified_hd is None                                 # proof dropped on the email change

    # (b2) an admin override on the account does not prove the mailbox
    await attrs.set_override(db, u, {"status": "matched", "is_officeholder": True, "level": "national",
                                     "department": "tabligh", "role": "mohtamim"}, "test", actor_user_id=1)
    await db.commit()
    assert await _signed_in(db, org, role_email) == (False, "not_signed_in")
    assert not attrs.is_address_proven(await attrs.get_row(db, 50), await db.get(User, 50))

    # (b3) a login whose hd belongs to another domain cannot create proof for this address
    await _login(db, 50, "other.example.invalid")
    assert await _signed_in(db, org, role_email) == (False, "not_signed_in")
    after = await _totals(db, org)
    assert after["not_signed_in"] == base["not_signed_in"] + 1 and after["expected"] == base["expected"]


@pytest.mark.asyncio
@pytest.mark.parametrize("a_email,role_email", PAIRS)
async def test_control_genuine_google_login_as_the_role_address_is_matched(db, org, world, a_email, role_email):
    await _seed_roster(db, org, world, role_email)
    await add_user(db, org.id, 51, role_email, 4, signup="google")
    await _login(db, 51, role_email.split("@")[1])
    assert await _signed_in(db, org, role_email) == (True, "not_started")
    u = await db.get(User, 51)
    assert attrs.is_address_proven(await attrs.get_row(db, 51), u)


@pytest.mark.asyncio
async def test_atfal_address_without_proof_stays_unrecognized_and_not_signed_in(db, org, world):
    await _seed_roster(db, org, world, ATFAL)
    # a password / invited account on an Atfal address: no Google login => no proof => no row, never matched
    await add_user(db, org.id, 52, ATFAL, 4, signup="email")
    await attrs.recompute_users(db, org_id=org.id)
    await db.commit()
    assert await _signed_in(db, org, ATFAL) == (False, "not_signed_in")
    assert _unrecognised((await attrs.read_effective(db, await db.get(User, 52)))[0])
    # a Google login whose hd does NOT match the domain proves nothing either
    await _login(db, 52, "wrong.example.invalid")
    assert await _signed_in(db, org, ATFAL) == (False, "not_signed_in")
    assert _unrecognised((await attrs.read_effective(db, await db.get(User, 52)))[0])
