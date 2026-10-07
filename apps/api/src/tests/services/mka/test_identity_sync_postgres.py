"""MKA fork: identity sync APPLY on a real Postgres (the SQLite unit tests skip the advisory lock and use JSON, not JSONB).

Skipped unless ``MKA_TEST_POSTGRES_URL`` is set, e.g. ``postgresql+asyncpg://postgres:x@127.0.0.1:5498/learnhouse``.
"""

import os
from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from src.db.mka_identity import MkaIdentitySyncState, MkaManagedGroup, MkaManagedRole
from src.db.organizations import Organization
from src.db.roles import Role, RoleTypeEnum
from src.services.mka import identity_sync as sync

PG_URL = os.environ.get("MKA_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="MKA_TEST_POSTGRES_URL not set")


@pytest.fixture
async def pg_factory(monkeypatch):
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ENABLED", "true")
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ORG_IDS", "1")
    eng = create_async_engine(PG_URL)
    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))  # the app does this at startup
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        now = str(datetime.now())
        s.add(Organization(id=1, name="Default", slug="default", email="o@example.invalid", org_uuid="org_pg",
                           creation_date=now, update_date=now))
        # setup.install_default_elements seeds the global roles with EXPLICIT ids 1-4, so the role id sequence still
        # starts at 1: the first sequence-assigned insert collides with the seeded Admin role.
        for rid in (1, 2, 3, 4):
            s.add(Role(id=rid, name=f"Global {rid}", description="d", role_type=RoleTypeEnum.TYPE_GLOBAL,
                       role_uuid=f"role_global_{rid}", rights={}, creation_date=now, update_date=now))
        await s.commit()
    yield factory
    await eng.dispose()


async def test_backfill_apply_on_postgres(pg_factory):
    async with pg_factory() as db:
        result = await sync.backfill_org(db, 1, dry_run=False)
        assert result["role_created"] is True
        assert result["groups_created"] == len(sync.catalogue())
    async with pg_factory() as db:
        binding = (await db.execute(select(MkaManagedRole))).scalars().one()
        assert binding.rights_version == sync.MOHTAMIM_RIGHTS_VERSION
        assert len((await db.execute(select(MkaManagedGroup))).scalars().all()) == len(sync.catalogue())
        assert (await db.get(MkaIdentitySyncState, 1)).last_sync_at is not None
    async with pg_factory() as db:  # idempotent
        again = await sync.backfill_org(db, 1, dry_run=False)
        assert again["groups_created"] == 0 and again["role_created"] is False
