"""MKA fork: the mka_user_attributes migration must be idempotent and match the models."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from src.db.mka_user_attributes import (
    MkaRosterOverride,
    MkaUserAttributes,
    MkaUserAttributesAudit,
)

MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "migrations" / "versions" / "mka_20261004_user_attributes.py"
)
MODELS = [MkaUserAttributes, MkaUserAttributesAudit, MkaRosterOverride]
TABLES = {m.__tablename__ for m in MODELS}


def _load():
    spec = importlib.util.spec_from_file_location("mka_attr_migration", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(sa.text('CREATE TABLE "user" (id INTEGER PRIMARY KEY)'))
    yield eng
    eng.dispose()


def _run(engine, fn):
    mod = _load()
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(mod, fn)()


def _state(engine):
    insp = sa.inspect(engine)
    out = {}
    for t in sorted(TABLES):
        if t in insp.get_table_names():
            out[t] = (
                sorted(c["name"] for c in insp.get_columns(t)),
                sorted(ix["name"] for ix in insp.get_indexes(t)),
            )
    return out


def test_revision_chain():
    mod = _load()
    assert mod.down_revision == "mka_20261004_user_profile"
    assert mod.revision == "mka_20261004_user_attributes"


def test_upgrade_creates_all_tables(engine):
    _run(engine, "upgrade")
    assert set(_state(engine)) == TABLES


def test_upgrade_twice_is_noop(engine):
    _run(engine, "upgrade")
    first = _state(engine)
    _run(engine, "upgrade")
    assert _state(engine) == first


def test_migration_matches_create_all(engine):
    """create_all (the API's startup bootstrap) and the migration agree on columns + index names."""
    other = sa.create_engine("sqlite://")
    with other.begin() as conn:
        conn.execute(sa.text('CREATE TABLE "user" (id INTEGER PRIMARY KEY)'))
    MkaUserAttributes.metadata.create_all(other, tables=[m.__table__ for m in MODELS])
    _run(engine, "upgrade")
    assert _state(engine) == _state(other)
    other.dispose()


def test_upgrade_after_create_all_bootstrap(engine):
    MkaUserAttributes.metadata.create_all(engine, tables=[m.__table__ for m in MODELS])
    before = _state(engine)
    _run(engine, "upgrade")
    assert _state(engine) == before


def test_upgrade_adds_only_missing_index(engine):
    MkaUserAttributes.metadata.create_all(engine, tables=[m.__table__ for m in MODELS])
    with engine.begin() as conn:
        conn.execute(sa.text("DROP INDEX ix_mka_user_attributes_eff_region"))
    _run(engine, "upgrade")
    idx = _state(engine)["mka_user_attributes"][1]
    assert "ix_mka_user_attributes_eff_region" in idx


def test_downgrade_removes_everything_and_repeat_is_noop(engine):
    _run(engine, "upgrade")
    _run(engine, "downgrade")
    assert _state(engine) == {}
    _run(engine, "downgrade")
    assert _state(engine) == {}
