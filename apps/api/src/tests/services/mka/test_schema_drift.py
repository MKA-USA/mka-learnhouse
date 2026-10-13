"""Schema drift comparator, Alembic head check, migrate helpers and the public health endpoint (sqlite, no Postgres)."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from src.routers import mka_health
from src.services.mka import schema_drift, schema_migrate


def _declared() -> MetaData:
    md = MetaData()
    Table("widget", md, Column("id", Integer, primary_key=True), Column("name", String), Column("order", Integer))
    Table("gadget", md, Column("id", Integer, primary_key=True))
    return md


@pytest.fixture
def conn():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.connect() as c:
        yield c


def test_no_drift_when_schema_matches(conn):
    _declared().create_all(conn)
    drift = schema_drift.compute_drift(conn, _declared())
    assert drift.ok and drift.count == 0 and drift.describe() == "none"


def test_missing_column_is_reported(conn):
    """The incident: a table exists (create_all) but lacks a column a newer migration adds."""
    conn.execute(text('CREATE TABLE widget (id INTEGER PRIMARY KEY, name VARCHAR)'))
    conn.execute(text("CREATE TABLE gadget (id INTEGER PRIMARY KEY)"))
    drift = schema_drift.compute_drift(conn, _declared())
    assert drift.missing_columns == [("widget", "order")]
    assert drift.missing_tables == []
    assert not drift.ok and drift.count == 1


def test_missing_table_is_reported(conn):
    conn.execute(text('CREATE TABLE widget (id INTEGER PRIMARY KEY, name VARCHAR, "order" INTEGER)'))
    drift = schema_drift.compute_drift(conn, _declared())
    assert drift.missing_tables == ["gadget"]
    assert drift.missing_columns == []


def test_extra_live_columns_are_not_drift(conn):
    _declared().create_all(conn)
    conn.execute(text("ALTER TABLE gadget ADD COLUMN legacy VARCHAR"))
    assert schema_drift.compute_drift(conn, _declared()).ok


def test_alembic_at_head(conn):
    heads = {"abc123"}
    assert schema_drift.alembic_at_head(conn, heads) is False  # no alembic_version table
    conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
    assert schema_drift.alembic_at_head(conn, heads) is False  # empty
    conn.execute(text("INSERT INTO alembic_version VALUES ('old999')"))
    assert schema_drift.alembic_at_head(conn, heads) is False  # behind
    conn.execute(text("DELETE FROM alembic_version"))
    conn.execute(text("INSERT INTO alembic_version VALUES ('abc123')"))
    assert schema_drift.alembic_at_head(conn, heads) is True


def test_repo_has_exactly_one_alembic_head():
    assert len(schema_drift.alembic_head_revisions()) == 1


def test_default_baseline_revision_exists():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(schema_drift.API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(schema_drift.API_ROOT / "migrations"))
    assert ScriptDirectory.from_config(cfg).get_revision(schema_migrate.DEFAULT_BASELINE_REV) is not None


def test_sync_url_strips_async_drivers():
    assert schema_migrate.sync_url("postgresql+asyncpg://u:p@h/db") == "postgresql://u:p@h/db"
    assert schema_migrate.sync_url("postgres://u:p@h/db") == "postgresql://u:p@h/db"
    assert schema_migrate.sync_url("postgresql://u:p@h/db") == "postgresql://u:p@h/db"


def test_classify_states():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    assert schema_migrate.classify(engine) == "fresh"
    with engine.begin() as c:
        c.execute(text("CREATE TABLE widget (id INTEGER)"))
    assert schema_migrate.classify(engine) == "unstamped"
    with engine.begin() as c:
        c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
    assert schema_migrate.classify(engine) == "unstamped"  # empty version table
    with engine.begin() as c:
        c.execute(text("INSERT INTO alembic_version VALUES ('x')"))
    assert schema_migrate.classify(engine) == "stamped"


def test_skip_env_short_circuits(monkeypatch, capsys):
    monkeypatch.setenv("MKA_SKIP_MIGRATIONS", "1")
    assert schema_migrate.run() == 0
    assert "skipped" in capsys.readouterr().out


def test_failure_is_logged_and_never_raises(monkeypatch, capsys):
    monkeypatch.delenv("MKA_SKIP_MIGRATIONS", raising=False)
    monkeypatch.setenv("LEARNHOUSE_SQL_CONNECTION_STRING", "postgresql://u:p@127.0.0.1:1/none")
    monkeypatch.setattr(schema_migrate, "wait_for_db", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert schema_migrate.run() == 0
    assert "MKA_MIGRATE_FAILED" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_health_endpoint_returns_counts_only(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as c:
        await c.execute(text("CREATE TABLE widget (id INTEGER PRIMARY KEY)"))
    monkeypatch.setattr(mka_health, "engine", engine)
    monkeypatch.setattr(mka_health, "_cache", {"at": 0.0, "value": None})
    app = FastAPI()
    app.include_router(mka_health.router, prefix="/mka/health")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/mka/health/schema")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"ok", "missing", "alembic_at_head"}
    assert body["ok"] is False and body["missing"] > 0 and body["alembic_at_head"] is False
    assert "widget" not in r.text
    await engine.dispose()
