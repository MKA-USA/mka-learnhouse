"""MKA fork: the mka_user_profile migration must be idempotent.

The API bootstraps missing tables with ``SQLModel.metadata.create_all`` at
startup, so a manual ``alembic upgrade head`` can meet a database where the
table and its indexes already exist. Runs the real migration through alembic's
``MigrationContext`` + ``Operations`` against in-memory SQLite (which ignores
``postgresql_where``).
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from src.db.mka_user_profile import MkaUserProfile

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations" / "versions" / "mka_20261004_user_profile.py"
)
TABLE = "mka_user_profile"
INDEXES = {
    "ix_mka_user_profile_amc_id",
    "ix_mka_user_profile_region",
    "ix_mka_user_profile_majlis",
}


def _load_migration():
    spec = importlib.util.spec_from_file_location("mka_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(sa.text('CREATE TABLE "user" (id INTEGER PRIMARY KEY)'))
    yield eng
    eng.dispose()


def _run(engine, fn_name):
    module = _load_migration()
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(module, fn_name)()


def _state(engine):
    insp = sa.inspect(engine)
    if TABLE not in insp.get_table_names():
        return False, []
    return True, sorted(ix["name"] for ix in insp.get_indexes(TABLE))


def test_upgrade_on_empty_db_creates_table_and_indexes(engine):
    _run(engine, "upgrade")
    exists, indexes = _state(engine)
    assert exists
    assert set(indexes) == INDEXES
    amc = next(
        ix for ix in sa.inspect(engine).get_indexes(TABLE)
        if ix["name"] == "ix_mka_user_profile_amc_id"
    )
    assert amc["unique"]


def test_upgrade_twice_is_noop(engine):
    _run(engine, "upgrade")
    _run(engine, "upgrade")
    exists, indexes = _state(engine)
    assert exists
    assert sorted(indexes) == sorted(INDEXES)  # no duplicates


def test_upgrade_after_create_all_bootstrap(engine):
    MkaUserProfile.metadata.create_all(engine, tables=[MkaUserProfile.__table__])
    exists, indexes = _state(engine)
    assert exists and set(indexes) == INDEXES  # create_all made the same names
    _run(engine, "upgrade")
    assert _state(engine) == (True, sorted(INDEXES))


def test_upgrade_adds_only_missing_index(engine):
    MkaUserProfile.metadata.create_all(engine, tables=[MkaUserProfile.__table__])
    with engine.begin() as conn:
        conn.execute(sa.text("DROP INDEX ix_mka_user_profile_region"))
    assert "ix_mka_user_profile_region" not in _state(engine)[1]
    _run(engine, "upgrade")
    assert _state(engine) == (True, sorted(INDEXES))


def test_downgrade_removes_everything_and_repeat_is_noop(engine):
    _run(engine, "upgrade")
    _run(engine, "downgrade")
    assert _state(engine) == (False, [])
    _run(engine, "downgrade")
    assert _state(engine) == (False, [])
