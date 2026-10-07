"""MKA fork: identity sync, Mohtamim role + managed groups (spec 2026-10-07 section 3.A). Synthetic example.invalid data."""

from types import SimpleNamespace

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.mka_identity import MkaIdentitySyncState, MkaManagedGroup, MkaManagedRole
from src.db.mka_user_attributes import MkaUserAttributes
from src.db.roles import Role, RoleTypeEnum
from src.db.user_organizations import UserOrganization
from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup
from src.services.mka import identity_sync as sync
from src.tests.routers.mka_compliance_world import add_attributes, add_user

NATIONAL_TABLIGH = dict(level="national", department="tabligh", role="mohtamim", role_title="Mohtamim Tabligh")
NAZIM_MAAL_ALBANY = dict(level="local", department="maal", role="nazim_dept", majlis="Albany", region="Northeast")


@pytest.fixture(autouse=True)
def flag_on(monkeypatch):
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ENABLED", "true")
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ORG_IDS", "1")  # the `org` fixture; `other_org` (id 2) is NOT allowlisted unless a test says so


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def make(db, org, uid, email, role_id=4, **eff):
    await add_user(db, org.id, uid, email, role_id=role_id)
    await add_attributes(db, uid, email, **eff)
    return SimpleNamespace(id=uid, email=email)


async def group_keys(db, org_id, uid):
    rows = (
        await db.execute(
            select(MkaManagedGroup.key)
            .join(UserGroupUser, UserGroupUser.usergroup_id == MkaManagedGroup.usergroup_id)
            .where(UserGroupUser.user_id == uid, UserGroupUser.org_id == org_id)
        )
    ).scalars().all()
    return sorted(rows)


async def role_of(db, org_id, uid):
    return (
        await db.execute(select(UserOrganization.role_id).where(UserOrganization.user_id == uid, UserOrganization.org_id == org_id))
    ).scalar_one()


async def snapshot(db):
    out = {}
    for model in (MkaManagedRole, MkaManagedGroup, UserGroup, UserGroupUser, Role, UserOrganization, MkaIdentitySyncState):
        out[model.__name__] = len((await db.execute(select(model))).scalars().all())
    return out


# --- catalogue -------------------------------------------------------------------------------------------------


def test_catalogue_shape():
    cat = sync.catalogue()
    kinds = [k.split(":")[0] for k in cat]
    assert kinds.count("majlis") == 52 and kinds.count("region") == 10 and kinds.count("department") == 20
    assert [k for k in cat if k.startswith("level:")] == ["level:national", "level:regional", "level:local"]
    assert cat["majlis:albany"] == "Majlis: Albany" and cat["region:northeast"] == "Region: Northeast"
    assert cat["department:maal"] == "Department: Maal" and cat["level:local"] == "Local Amila"
    assert "department:atfal" not in cat and "department:muqami" not in cat


def test_desired_groups_unknown_values_are_ignored():
    cat = sync.catalogue()
    assert sync.desired_group_keys({"majlis": "Nowhere", "region": "Mars", "department": "zzz", "level": "galactic",
                                    "is_officeholder": True}, cat) == set()
    assert sync.desired_group_keys({"level": "local", "is_officeholder": False}, cat) == set()  # level needs an officeholder


# --- role ------------------------------------------------------------------------------------------------------


async def test_role_is_created_once_and_rights_are_what_the_spec_says(db, org):
    c1 = await sync.ensure_org(db, org.id)
    c2 = await sync.ensure_org(db, org.id)
    assert c1.role_created and c1.groups_created == 85 and c1.role_id == c2.role_id
    assert not c2.role_created and c2.groups_created == 0
    roles = (await db.execute(select(Role).where(Role.org_id == org.id, Role.name == "Mohtamim"))).scalars().all()
    assert len(roles) == 1 and roles[0].role_type == RoleTypeEnum.TYPE_ORGANIZATION
    r = roles[0].rights
    assert r["courses"]["action_create"] and r["courses"]["action_update_own"]
    assert not r["courses"]["action_update"] and not r["courses"]["action_delete"]  # no rights over other people's courses
    for res in ("coursechapters", "activities", "assignments"):
        assert r[res]["action_create"] and r[res]["action_read"] and r[res]["action_update"] and not r[res]["action_delete"]
    for res in ("media", "folders"):  # create + read only: update/delete would reach every org member's files
        assert r[res] == {"action_create": True, "action_read": True, "action_update": False, "action_delete": False}
    assert r["usergroups"] == {"action_create": False, "action_read": True, "action_update": False, "action_delete": False}
    assert r["dashboard"]["action_access"] and r["organizations"]["action_read"] and not r["organizations"]["action_update"]
    assert not any(r["users"].values()) and not any(r["roles"].values())


async def test_rights_are_rewritten_only_when_the_version_bumps(db, org, monkeypatch):
    ctx = await sync.ensure_org(db, org.id)
    role = await db.get(Role, ctx.role_id)
    role.rights = {**role.rights, "marker": "admin edit"}
    db.add(role)
    await db.commit()
    await sync.ensure_org(db, org.id)
    assert (await db.get(Role, ctx.role_id)).rights.get("marker") == "admin edit"  # same version: left alone

    bumped = sync.MOHTAMIM_RIGHTS_VERSION + 1
    monkeypatch.setattr(sync, "MOHTAMIM_RIGHTS_VERSION", bumped)
    again = await sync.ensure_org(db, org.id)
    assert again.role_updated and again.role_id == ctx.role_id
    await db.refresh(role)
    assert "marker" not in role.rights
    binding = (await db.execute(select(MkaManagedRole).where(MkaManagedRole.org_id == org.id))).scalars().one()
    assert binding.rights_version == bumped
    assert len((await db.execute(select(Role).where(Role.name == "Mohtamim"))).scalars().all()) == 1


async def test_an_existing_role_named_mohtamim_is_adopted_not_duplicated(db, org):
    db.add(Role(name="Mohtamim", org_id=org.id, role_type=RoleTypeEnum.TYPE_ORGANIZATION, role_uuid="role_x", rights={}))
    await db.commit()
    ctx = await sync.ensure_org(db, org.id)
    assert ctx.role_updated and not ctx.role_created
    assert len((await db.execute(select(Role).where(Role.name == "Mohtamim"))).scalars().all()) == 1


async def test_a_deleted_group_is_recreated_and_renames_do_not_matter(db, org):
    ctx = await sync.ensure_org(db, org.id)
    renamed = await db.get(UserGroup, ctx.groups["region:east"])
    renamed.name = "Our East"
    db.add(renamed)
    gone = await db.get(UserGroup, ctx.groups["region:gulf"])
    await db.delete(gone)
    await db.commit()
    again = await sync.ensure_org(db, org.id)
    assert again.groups_recreated == 1 and again.groups_created == 0 and again.groups["region:east"] == ctx.groups["region:east"]
    assert again.groups["region:gulf"] != ctx.groups["region:gulf"]
    assert (await db.get(UserGroup, ctx.groups["region:east"])).name == "Our East"
    binding = (await db.execute(select(MkaManagedGroup).where(MkaManagedGroup.key == "region:gulf"))).scalars().one()
    assert binding.usergroup_id == again.groups["region:gulf"]  # same key, new group


async def test_backfill_reports_recreated_groups_and_dry_run_previews_them(db, org):
    ctx = await sync.ensure_org(db, org.id)
    await db.delete(await db.get(UserGroup, ctx.groups["majlis:albany"]))
    await db.commit()
    dry = await sync.backfill_org(db, org.id, dry_run=True)
    assert dry["groups_recreated"] == 1 and dry["groups_created"] == 0
    assert (await sync.ensure_org(db, org.id, dry_run=True)).groups["majlis:albany"] is None  # nothing written
    done = await sync.backfill_org(db, org.id, dry_run=False)
    assert done["groups_recreated"] == 1 and done["groups_created"] == 0
    assert (await sync.backfill_org(db, org.id, dry_run=False))["groups_recreated"] == 0


async def test_login_sync_recreates_a_deleted_group_it_needs(db, org, factory):
    u = await make(db, org, 60, "maal.albany@example.invalid", is_officeholder=True, **NAZIM_MAAL_ALBANY)
    ctx = await sync.ensure_org(db, org.id)
    await db.delete(await db.get(UserGroup, ctx.groups["majlis:albany"]))
    await db.commit()
    await sync.identity_sync_user(factory, u)
    assert "majlis:albany" in await group_keys(db, org.id, 60)


# --- per-user sync -----------------------------------------------------------------------------------------------


async def test_local_nazim_lands_in_exactly_four_groups_and_keeps_role_user(db, org):
    u = await make(db, org, 10, "maal.albany@example.invalid", is_officeholder=True, **NAZIM_MAAL_ALBANY)
    plan = await sync.sync_user_identity(db, org.id, u)
    assert plan.role is None
    assert await group_keys(db, org.id, 10) == ["department:maal", "level:local", "majlis:albany", "region:northeast"]
    assert await role_of(db, org.id, 10) == 4


async def test_national_mohtamim_gets_the_role_and_department_and_level_groups(db, org, monkeypatch):
    dropped = []
    monkeypatch.setattr(sync, "_invalidate_session", dropped.append)
    u = await make(db, org, 11, "tabligh@example.invalid", is_officeholder=True, **NATIONAL_TABLIGH)
    plan = await sync.sync_user_identity(db, org.id, u)
    ctx = await sync.ensure_org(db, org.id)
    assert plan.role == "set" and await role_of(db, org.id, 11) == ctx.role_id
    assert await group_keys(db, org.id, 11) == ["department:tabligh", "level:national"]
    assert dropped == [11]


async def test_naib_mohtamim_qualifies_too(db, org):
    u = await make(db, org, 12, "naib.tabligh@example.invalid", is_officeholder=True,
                   level="national", department="tabligh", role="naib_mohtamim")
    await sync.sync_user_identity(db, org.id, u)
    assert await role_of(db, org.id, 12) == (await sync.ensure_org(db, org.id)).role_id


@pytest.mark.parametrize("held", [1, 2, 3, 77])
async def test_admins_instructors_and_other_roles_are_never_changed(db, org, held):
    u = await make(db, org, 13, "tabligh@example.invalid", role_id=held, is_officeholder=True, **NATIONAL_TABLIGH)
    plan = await sync.sync_user_identity(db, org.id, u)
    assert plan.role is None and await role_of(db, org.id, 13) == held
    assert await group_keys(db, org.id, 13) == ["department:tabligh", "level:national"]  # groups still follow the mailbox


async def test_attribute_change_moves_groups_and_reverts_the_role(db, org):
    u = await make(db, org, 14, "tabligh@example.invalid", is_officeholder=True, **NATIONAL_TABLIGH)
    await sync.sync_user_identity(db, org.id, u)
    ctx = await sync.ensure_org(db, org.id)
    assert await role_of(db, org.id, 14) == ctx.role_id

    row = await db.get(MkaUserAttributes, 14)
    row.effective = {**row.effective, **NAZIM_MAAL_ALBANY, "is_officeholder": True}
    db.add(row)
    await db.commit()
    plan = await sync.sync_user_identity(db, org.id, u)
    assert plan.role == "revert" and await role_of(db, org.id, 14) == 4
    assert await group_keys(db, org.id, 14) == ["department:maal", "level:local", "majlis:albany", "region:northeast"]


async def test_unmanaged_groups_are_never_touched(db, org):
    u = await make(db, org, 15, "maal.albany@example.invalid", is_officeholder=True, **NAZIM_MAAL_ALBANY)
    mine = UserGroup(name="Book club", description="d", org_id=org.id, usergroup_uuid="usergroup_mine")
    db.add(mine)
    await db.commit()
    db.add(UserGroupUser(usergroup_id=mine.id, user_id=15, org_id=org.id))
    await db.commit()
    await sync.sync_user_identity(db, org.id, u)
    row = await db.get(MkaUserAttributes, 15)
    row.effective = {**row.effective, "majlis": None, "region": None, "department": None, "is_officeholder": False}
    db.add(row)
    await db.commit()
    await sync.sync_user_identity(db, org.id, u)
    assert await group_keys(db, org.id, 15) == []
    kept = (await db.execute(select(UserGroupUser).where(UserGroupUser.usergroup_id == mine.id))).scalars().all()
    assert len(kept) == 1


async def test_disabled_flag_means_zero_writes(db, org, factory, monkeypatch):
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ENABLED", "false")
    u = await make(db, org, 16, "tabligh@example.invalid", is_officeholder=True, **NATIONAL_TABLIGH)
    before = await snapshot(db)
    assert (await sync.sync_user_identity(db, org.id, u)).skipped == "disabled"
    await sync.identity_sync_user(factory, u)
    assert await snapshot(db) == before


async def test_second_run_performs_zero_writes(db, org, engine):
    u = await make(db, org, 17, "tabligh@example.invalid", is_officeholder=True, **NATIONAL_TABLIGH)
    await sync.sync_user_identity(db, org.id, u)
    writes = []

    def spy(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement[:60])

    event.listen(engine.sync_engine, "before_cursor_execute", spy)
    try:
        plan = await sync.sync_user_identity(db, org.id, u)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", spy)
    assert not plan.changed and writes == []


async def test_unproven_or_stale_identity_is_skipped_and_nothing_is_removed(db, org):
    u = await make(db, org, 18, "maal.albany@example.invalid", is_officeholder=True, **NAZIM_MAAL_ALBANY)
    await sync.sync_user_identity(db, org.id, u)
    row = await db.get(MkaUserAttributes, 18)
    row.stale = True
    db.add(row)
    await db.commit()
    assert (await sync.sync_user_identity(db, org.id, u)).skipped == "unproven"
    assert len(await group_keys(db, org.id, 18)) == 4

    row.stale = False
    row.verified_hd = None
    db.add(row)
    await db.commit()
    assert (await sync.sync_user_identity(db, org.id, u)).skipped == "unproven"

    row.verified_hd = "example.invalid"
    row.rules_version = "2026.3"  # awaiting recompute after a rules bump: reads as unrecognized, must not wipe groups
    db.add(row)
    await db.commit()
    assert (await sync.sync_user_identity(db, org.id, u)).skipped == "stale"
    assert len(await group_keys(db, org.id, 18)) == 4


async def test_a_user_with_no_attribute_row_does_not_create_anything(db, org):
    await add_user(db, org.id, 19, "x@example.invalid")
    before = await snapshot(db)
    assert (await sync.sync_user_identity(db, org.id, SimpleNamespace(id=19, email="x@example.invalid"))).skipped == "no_attributes"
    assert await snapshot(db) == before


async def test_login_wrapper_never_raises(db, org, factory, monkeypatch):
    u = await make(db, org, 20, "tabligh@example.invalid", is_officeholder=True, **NATIONAL_TABLIGH)

    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(sync, "ensure_org", boom)
    await sync.identity_sync_user(factory, u)  # swallowed
    monkeypatch.undo()
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ENABLED", "true")
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ORG_IDS", "1")
    await sync.identity_sync_user(factory, u)
    assert await group_keys(db, org.id, 20) == ["department:tabligh", "level:national"]


async def test_the_login_hook_runs_the_sync_after_the_refresh(db, org, factory, monkeypatch):
    from src.services.mka import attributes as attrs

    called = []

    async def fake(factory_, snap):
        called.append(snap.id)

    monkeypatch.setattr(sync, "identity_sync_user", fake)
    await attrs._identity_sync_after_refresh(db, SimpleNamespace(id=5, email="a@example.invalid"))
    assert called == [5]
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ENABLED", "false")
    await attrs._identity_sync_after_refresh(db, SimpleNamespace(id=6, email="a@example.invalid"))
    assert called == [5]


# --- backfill ----------------------------------------------------------------------------------------------------


async def test_backfill_dry_run_writes_nothing_and_apply_is_idempotent(db, org, other_org):
    await make(db, org, 30, "maal.albany@example.invalid", is_officeholder=True, **NAZIM_MAAL_ALBANY)
    await make(db, org, 31, "tabligh@example.invalid", is_officeholder=True, **NATIONAL_TABLIGH)
    await add_user(db, org.id, 32, "plain@example.invalid")  # member without an attribute row: not seen
    await make(db, other_org, 33, "maal.albany2@example.invalid", is_officeholder=True, **NAZIM_MAAL_ALBANY)

    before = await snapshot(db)
    dry = await sync.backfill_org(db, org.id, dry_run=True)
    assert await snapshot(db) == before
    assert dry["dry_run"] and dry["users_seen"] == 2 and dry["groups_created"] == 85 and dry["role_created"]
    assert dry["memberships_added"] == 6 and dry["roles_set"] == 1 and dry["errors"] == 0
    assert {p["user_id"] for p in dry["planned"]} == {30, 31}

    applied = await sync.backfill_org(db, org.id, dry_run=False)
    assert {k: applied[k] for k in ("users_seen", "groups_created", "memberships_added", "memberships_removed",
                                    "roles_set", "roles_reverted", "errors")} == {
        "users_seen": 2, "groups_created": 85, "memberships_added": 6, "memberships_removed": 0,
        "roles_set": 1, "roles_reverted": 0, "errors": 0}
    assert await group_keys(db, org.id, 30) == ["department:maal", "level:local", "majlis:albany", "region:northeast"]
    assert await group_keys(db, other_org.id, 33) == []  # other org untouched
    assert (await db.get(MkaIdentitySyncState, org.id)).last_counts["memberships_added"] == 6

    again = await sync.backfill_org(db, org.id, dry_run=False)
    assert again["groups_created"] == 0 and again["memberships_added"] == 0 and again["roles_set"] == 0
    assert again["memberships_removed"] == 0 and not again["role_created"]


async def test_status_reports_flag_role_groups_and_last_sync(db, org):
    before = await sync.status(db, org.id)
    assert before["enabled"] and before["role_id"] is None and before["groups"] == 0 and before["last_sync_at"] is None
    await make(db, org, 40, "tabligh@example.invalid", is_officeholder=True, **NATIONAL_TABLIGH)
    await sync.backfill_org(db, org.id, dry_run=False)
    after = await sync.status(db, org.id)
    assert after["role_id"] and after["groups"] == 85 == after["groups_expected"] and after["last_sync_at"]


async def test_an_existing_role_at_the_old_rights_version_is_narrowed(db, org):
    ctx = await sync.ensure_org(db, org.id)
    role = await db.get(Role, ctx.role_id)
    role.rights = {**role.rights, "media": {"action_create": True, "action_read": True, "action_update": True, "action_delete": True}}
    db.add(role)
    binding = (await db.execute(select(MkaManagedRole).where(MkaManagedRole.org_id == org.id))).scalars().one()
    binding.rights_version = 1  # what PR #30's first head stored
    db.add(binding)
    await db.commit()
    again = await sync.ensure_org(db, org.id)
    assert again.role_updated
    await db.refresh(role)
    assert role.rights["media"]["action_update"] is False and role.rights["folders"]["action_delete"] is False


# --- org allowlist (MKA_IDENTITY_SYNC_ORG_IDS) -------------------------------------------------------------------


async def test_unset_allowlist_syncs_nothing_and_a_non_allowlisted_org_gets_zero_writes(db, org, other_org, factory, monkeypatch):
    u = await make(db, other_org, 70, "tabligh@example.invalid", is_officeholder=True, **NATIONAL_TABLIGH)
    before = await snapshot(db)
    assert (await sync.sync_user_identity(db, other_org.id, u)).skipped == "org_not_allowed"
    await sync.identity_sync_user(factory, u)
    assert await snapshot(db) == before

    monkeypatch.delenv("MKA_IDENTITY_SYNC_ORG_IDS")  # unset = no org at all
    assert sync.allowed_org_ids() == frozenset()
    v = await make(db, org, 71, "tabligh2@example.invalid", is_officeholder=True, **NATIONAL_TABLIGH)
    before = await snapshot(db)
    assert (await sync.sync_user_identity(db, org.id, v)).skipped == "org_not_allowed"
    await sync.identity_sync_user(factory, v)
    assert await snapshot(db) == before
    with pytest.raises(sync.OrgNotAllowed):
        await sync.ensure_org(db, org.id)
    with pytest.raises(sync.OrgNotAllowed):
        await sync.backfill_org(db, org.id, dry_run=False)
    assert (await sync.status(db, org.id))["orgs_allowed"] == []


async def test_dry_run_on_a_non_allowlisted_org_reports_it_and_writes_nothing(db, other_org):
    await make(db, other_org, 72, "tabligh@example.invalid", is_officeholder=True, **NATIONAL_TABLIGH)
    before = await snapshot(db)
    dry = await sync.backfill_org(db, other_org.id, dry_run=True)
    assert dry["org_allowed"] is False and dry["roles_set"] == 1 and await snapshot(db) == before
    with pytest.raises(sync.OrgNotAllowed):
        await sync.backfill_org(db, other_org.id, dry_run=False)
    assert (await sync.status(db, other_org.id))["orgs_allowed"] == [1]


async def test_a_roster_or_override_layer_in_one_org_grants_nothing_in_another(db, org, other_org, factory, monkeypatch):
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ORG_IDS", "1,2")
    u = await make(db, org, 73, "someone@example.invalid", is_officeholder=True, **NATIONAL_TABLIGH)  # effective: an override
    db.add(UserOrganization(user_id=73, org_id=other_org.id, role_id=4, creation_date="x", update_date="x"))
    await db.commit()
    row = await db.get(MkaUserAttributes, 73)
    row.derived = {"status": "unrecognized", "is_officeholder": None, "level": None, "role": None, "department": None}
    db.add(row)
    await db.commit()
    await sync.identity_sync_user(factory, u)
    assert await role_of(db, org.id, 73) == 4 and await role_of(db, other_org.id, 73) == 4
    assert await group_keys(db, other_org.id, 73) == ["department:tabligh", "level:national"]  # groups (not the role) follow effective

    row = await db.get(MkaUserAttributes, 73)  # the PARSER says Mohtamim: both orgs may grant
    row.derived = {"status": "matched", "is_officeholder": True, **{k: NATIONAL_TABLIGH[k] for k in ("level", "role", "department")}}
    db.add(row)
    await db.commit()
    await sync.identity_sync_user(factory, u)
    assert await role_of(db, org.id, 73) != 4 and await role_of(db, other_org.id, 73) != 4


# --- fail-closed revert -----------------------------------------------------------------------------------------


async def holder(db, org, uid, email="tabligh@example.invalid", **eff):
    """A user who currently HOLDS the managed role."""
    ctx = await sync.ensure_org(db, org.id)
    u = await make(db, org, uid, email, role_id=ctx.role_id, is_officeholder=True, **{**NATIONAL_TABLIGH, **eff})
    return u, ctx


async def mutate(db, uid, **fields):
    row = await db.get(MkaUserAttributes, uid)
    for k, v in fields.items():
        setattr(row, k, v)
    db.add(row)
    await db.commit()


@pytest.mark.parametrize("fields", [
    {"verified_hd": None},                 # unproven
    {"stale": True},                       # refresh failed / marked stale
    {"rules_version": "2026.3"},           # rules bump awaiting recompute
    {"email_seen": "someone.else@example.invalid"},  # address no longer the account's
], ids=["unproven", "stale-flag", "rules-bump", "address-changed"])
async def test_an_untrusted_identity_loses_the_managed_role_but_keeps_its_groups(db, org, fields):
    u, ctx = await holder(db, org, 80)
    await sync.sync_user_identity(db, org.id, u)  # trusted run: groups in place
    groups = await group_keys(db, org.id, 80)
    assert groups and await role_of(db, org.id, 80) == ctx.role_id
    await mutate(db, 80, **fields)
    plan = await sync.sync_user_identity(db, org.id, u)
    assert plan.role == "revert" and plan.skipped
    assert await role_of(db, org.id, 80) == 4
    assert await group_keys(db, org.id, 80) == groups  # groups untouched


async def test_a_holder_with_no_attribute_row_is_reverted(db, org):
    u, ctx = await holder(db, org, 81)
    await db.delete(await db.get(MkaUserAttributes, 81))
    await db.commit()
    assert (await sync.sync_user_identity(db, org.id, u)).skipped == "no_attributes"
    assert await role_of(db, org.id, 81) == 4


async def test_the_revert_never_touches_other_roles_and_needs_flag_and_allowlist(db, org, monkeypatch):
    for rid in (1, 2, 3, 4):  # the built-in global roles, so the managed role does not take id 1 in this empty database
        db.add(Role(id=rid, name=f"global{rid}", role_type=RoleTypeEnum.TYPE_GLOBAL, role_uuid=f"role_g{rid}", rights={}))
    await db.commit()
    admin, _ = await holder(db, org, 82)
    await mutate(db, 82, verified_hd=None)
    await db.execute(UserOrganization.__table__.update().where(UserOrganization.user_id == 82).values(role_id=1))
    await db.commit()
    await sync.sync_user_identity(db, org.id, admin)
    assert await role_of(db, org.id, 82) == 1  # an admin is never changed

    u, ctx = await holder(db, org, 83, "tabligh3@example.invalid")
    await mutate(db, 83, verified_hd=None)
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ENABLED", "false")
    await sync.sync_user_identity(db, org.id, u)
    assert await role_of(db, org.id, 83) == ctx.role_id  # flag off: zero writes, even reverts
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ENABLED", "true")
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ORG_IDS", "99")
    await sync.sync_user_identity(db, org.id, u)
    assert await role_of(db, org.id, 83) == ctx.role_id  # org not allowlisted: no writes
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ORG_IDS", "1")
    await sync.sync_user_identity(db, org.id, u)
    assert await role_of(db, org.id, 83) == 4


async def test_login_wrapper_reverts_an_untrusted_holder(db, org, factory):
    u, _ = await holder(db, org, 84)
    await mutate(db, 84, stale=True)
    await sync.identity_sync_user(factory, u)
    assert await role_of(db, org.id, 84) == 4


async def test_the_login_hook_runs_the_sync_even_when_the_refresh_fails(db, org, monkeypatch):
    from src.security.session_context import AUTH_METHOD_GOOGLE
    from src.services.mka import attributes as attrs

    called = []

    async def boom(*a, **k):
        raise RuntimeError("refresh down")

    async def fake(factory_, snap):
        called.append(snap.id)

    monkeypatch.setattr(attrs, "refresh_attributes", boom)
    monkeypatch.setattr(sync, "identity_sync_user", fake)
    await add_user(db, org.id, 85, "tabligh@example.invalid")
    user = SimpleNamespace(id=85, email="tabligh@example.invalid", signup_method="google")
    await attrs.mka_refresh_on_login(db, user, AUTH_METHOD_GOOGLE)
    assert called == [85]


async def test_backfill_reverts_holders_with_and_without_a_row_and_dry_run_previews(db, org):
    ok, ctx = await holder(db, org, 86)
    _bad, _ = await holder(db, org, 87, "tabligh4@example.invalid")
    await mutate(db, 87, verified_hd=None)
    _orphan, _ = await holder(db, org, 88, "tabligh5@example.invalid")
    await db.delete(await db.get(MkaUserAttributes, 88))
    await db.commit()

    dry = await sync.backfill_org(db, org.id, dry_run=True)
    assert dry["roles_reverted"] == 2 and {p["user_id"] for p in dry["planned"]} >= {87, 88}
    assert await role_of(db, org.id, 87) == ctx.role_id and await role_of(db, org.id, 88) == ctx.role_id
    done = await sync.backfill_org(db, org.id, dry_run=False)
    assert done["roles_reverted"] == 2 and done["errors"] == 0
    assert await role_of(db, org.id, 87) == 4 and await role_of(db, org.id, 88) == 4
    assert await role_of(db, org.id, 86) == ctx.role_id  # the trusted holder keeps it
    assert (await sync.backfill_org(db, org.id, dry_run=False))["roles_reverted"] == 0
