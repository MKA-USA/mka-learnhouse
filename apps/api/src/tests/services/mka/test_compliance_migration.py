"""MKA fork: the mka_compliance migration must be idempotent and match the models."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse, MkaComplianceExpected

MIGRATION = (
    Path(__file__).resolve().parents[4] / "migrations" / "versions" / "mka_20261004_compliance.py"
)
MODELS = [MkaComplianceCycle, MkaComplianceCycleCourse, MkaComplianceExpected]
TABLES = {m.__tablename__ for m in MODELS}


def _load():
    spec = importlib.util.spec_from_file_location("mka_compliance_migration", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite://")
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
                sorted(u["name"] for u in insp.get_unique_constraints(t)),
            )
    return out


def test_revision_chain():
    mod = _load()
    assert mod.down_revision == "mka_20261004_user_attributes"
    assert mod.revision == "mka_20261004_compliance"


def test_every_table_is_org_scoped():
    for model in MODELS:
        assert "org_id" in model.__table__.columns, model.__tablename__
        assert not model.__table__.columns["org_id"].nullable


def test_upgrade_creates_all_tables(engine):
    _run(engine, "upgrade")
    assert set(_state(engine)) == TABLES


def test_upgrade_twice_is_noop(engine):
    _run(engine, "upgrade")
    first = _state(engine)
    _run(engine, "upgrade")
    assert _state(engine) == first


def test_migration_matches_create_all(engine):
    other = sa.create_engine("sqlite://")
    MkaComplianceCycle.metadata.create_all(other, tables=[m.__table__ for m in MODELS])
    _run(engine, "upgrade")
    assert _state(engine) == _state(other)
    other.dispose()


def test_upgrade_after_create_all_bootstrap(engine):
    MkaComplianceCycle.metadata.create_all(engine, tables=[m.__table__ for m in MODELS])
    before = _state(engine)
    _run(engine, "upgrade")
    assert _state(engine) == before


def test_upgrade_adds_only_missing_index(engine):
    MkaComplianceCycle.metadata.create_all(engine, tables=[m.__table__ for m in MODELS])
    with engine.begin() as conn:
        conn.execute(sa.text("DROP INDEX ix_mka_compliance_expected_email"))
    _run(engine, "upgrade")
    assert "ix_mka_compliance_expected_email" in _state(engine)["mka_compliance_expected"][1]


def test_downgrade_removes_everything_and_repeat_is_noop(engine):
    _run(engine, "upgrade")
    _run(engine, "downgrade")
    assert _state(engine) == {}
    _run(engine, "downgrade")
    assert _state(engine) == {}
