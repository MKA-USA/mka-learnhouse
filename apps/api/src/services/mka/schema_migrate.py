"""MKA fork: bring the database to the Alembic head at container start (``python -m src.services.mka.schema_migrate``).

Upstream applies migrations only through its CLI ``learnhouse update`` (see apps/cli/src/commands/update-ee.ts:
``ensureAlembicBaseline`` + ``runAlembicUpgrade``). Our Coolify deploys bypass that CLI and the API itself only runs
``create_all`` (creates tables, never columns), so migrations that add columns never ran. This ports that logic:

* fresh database (no application tables): ``create_all`` then stamp the head (upstream: the app creates the schema, the
  CLI stamps ``heads``).
* tables but no ``alembic_version`` (a ``create_all`` install): upstream stamps ``heads`` of the *outgoing* image BEFORE
  pulling the new one, so only the delta is applied. In-container we only know the NEW code, and stamping its heads
  would skip the new migrations (exactly the ``assignmenttask.order`` bug), so we stamp ``MKA_MIGRATE_BASELINE_REV``
  (default: the last fork head before the v1.4.0 upstream merge) and upgrade from there. All migrations after that
  revision are guarded by inspector checks, so re-running them against a ``create_all`` schema is a no-op.
* ``alembic upgrade heads`` under a Postgres advisory lock so concurrent containers never migrate together.
* Any failure is logged as ``MKA_MIGRATE_FAILED`` and the process still exits 0: the app must boot (no prod crash
  loop); ``/api/v1/mka/health/schema`` and the deploy workflows surface the failure.

Env: ``MKA_SKIP_MIGRATIONS=1`` skips everything; ``MKA_MIGRATE_BASELINE_REV`` overrides the baseline for unstamped DBs;
``MKA_MIGRATE_LOCK_TIMEOUT`` (seconds, default 300) bounds the wait for the advisory lock.
"""

from __future__ import annotations

import os
import sys
import time

from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

from src.services.mka import schema_drift



def log_line(level: str, msg: str, *args) -> None:
    """print() not logging: migrations/env.py calls fileConfig(), which disables pre-existing loggers."""
    print(f"{level} {msg % args if args else msg}", flush=True)


class _Log:
    info = staticmethod(lambda m, *a: log_line("INFO", m, *a))
    warning = staticmethod(lambda m, *a: log_line("WARN", m, *a))
    error = staticmethod(lambda m, *a: log_line("ERROR", m, *a))


log = _Log()

# Last fork head before the v1.4.0 upstream merge (c39b2b2c). Every migration after it is inspector-guarded.
DEFAULT_BASELINE_REV = "mka_20261008_course_audience"
ADVISORY_LOCK_KEY = 0x4D4B414D  # "MKAM"


def sync_url(url: str) -> str:
    """Alembic/psycopg2 URL from the app's connection string (strip async drivers, normalise legacy schemes)."""
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


def _alembic_config():
    from alembic.config import Config

    cfg = Config(str(schema_drift.API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(schema_drift.API_ROOT / "migrations"))
    return cfg


def wait_for_db(engine: Engine, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            if time.monotonic() >= deadline:
                raise RuntimeError(f"database not reachable after {timeout:.0f}s: {exc}") from exc
            time.sleep(2)


def classify(engine: Engine) -> str:
    """'fresh' | 'unstamped' | 'stamped'."""
    with engine.connect() as conn:
        insp = sa_inspect(conn)
        tables = set(insp.get_table_names()) - {"alembic_version"}
        if not tables:
            return "fresh"
        if "alembic_version" in insp.get_table_names():
            if conn.exec_driver_sql("SELECT count(*) FROM alembic_version").scalar():
                return "stamped"
        return "unstamped"


def migrate(engine: Engine, baseline_rev: str | None = None) -> str:
    """Run the migration plan. Returns the starting state. Caller holds the advisory lock."""
    from alembic import command

    cfg = _alembic_config()
    state = classify(engine)
    baseline = baseline_rev or os.environ.get("MKA_MIGRATE_BASELINE_REV") or DEFAULT_BASELINE_REV
    if state == "fresh":
        log.info("MKA_MIGRATE fresh database: create_all + stamp heads")
        with engine.begin() as conn:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            except Exception as exc:  # noqa: BLE001
                log.warning("pgvector extension unavailable: %s", exc)
        schema_drift.load_models()
        SQLModel.metadata.create_all(engine)
        command.stamp(cfg, "heads")
        return state
    if state == "unstamped":
        log.info("MKA_MIGRATE database has no alembic_version (create_all install): stamping baseline %s", baseline)
        command.stamp(cfg, baseline)
    command.upgrade(cfg, "heads")
    return state


def report_drift(engine: Engine) -> schema_drift.SchemaDrift:
    schema_drift.load_models()
    with engine.connect() as conn:
        drift = schema_drift.compute_drift(conn)
        at_head = schema_drift.alembic_at_head(conn)
    if drift.ok and at_head:
        log.info("MKA_SCHEMA_OK no drift, alembic at head")
    else:
        log.error("MKA_SCHEMA_DRIFT missing=%d alembic_at_head=%s details=[%s]", drift.count, at_head, drift.describe())
    return drift


def run() -> int:
    if os.environ.get("MKA_SKIP_MIGRATIONS", "").strip().lower() in ("1", "true", "yes", "on"):
        log.info("MKA_MIGRATE skipped (MKA_SKIP_MIGRATIONS set)")
        return 0
    url = os.environ.get("LEARNHOUSE_SQL_CONNECTION_STRING")
    if not url:
        log.error("MKA_MIGRATE_FAILED LEARNHOUSE_SQL_CONNECTION_STRING is not set")
        return 0
    os.chdir(schema_drift.API_ROOT)  # migrations/env.py scans the relative path src/db
    engine = None
    try:
        engine = create_engine(sync_url(url), pool_pre_ping=True)
        wait_for_db(engine)
        lock_timeout = float(os.environ.get("MKA_MIGRATE_LOCK_TIMEOUT", "300"))
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock_conn:
            deadline = time.monotonic() + lock_timeout
            while not lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY}).scalar():
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"could not get migration advisory lock within {lock_timeout:.0f}s")
                time.sleep(2)
            try:
                state = migrate(engine)
                log.info("MKA_MIGRATE_OK started from %s state", state)
            finally:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})
        report_drift(engine)
    except Exception as exc:  # noqa: BLE001
        log.error("MKA_MIGRATE_FAILED %s: %s", type(exc).__name__, str(exc)[:1500])
    finally:
        if engine is not None:
            engine.dispose()
    return 0  # never block app start; health/schema + deploy checks surface failures


if __name__ == "__main__":
    sys.exit(run())
