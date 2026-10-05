"""MKA fork: the mka_automation migration must be idempotent and match the models (contract section 3)."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from src.db.mka_automation import MkaAutomationEvent, MkaAutomationSendLog

API_DIR = Path(__file__).resolve().parents[4]
MIGRATION = API_DIR / "migrations" / "versions" / "mka_20261005_automation.py"
MODELS = [MkaAutomationEvent, MkaAutomationSendLog]
TABLES = {m.__tablename__ for m in MODELS}


def _load():
    spec = importlib.util.spec_from_file_location("mka_automation_migration", MIGRATION)
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


def test_revision_chain_is_a_single_head_after_compliance():
    mod = _load()
    assert mod.revision == "mka_20261005_automation"
    assert mod.down_revision == "mka_20261004_compliance"
    script = ScriptDirectory(str(API_DIR / "migrations"))
    # Single linear chain; later revisions may be stacked on top of automation.
    heads = script.get_heads()
    assert len(heads) == 1
    assert "mka_20261005_automation" in {r.revision for r in script.walk_revisions(head=heads[0])}


def test_every_table_is_org_scoped_and_cascades():
    for model in MODELS:
        col = model.__table__.columns["org_id"]
        assert not col.nullable, model.__tablename__
        fks = list(col.foreign_keys)
        assert len(fks) == 1 and fks[0].column.table.name == "organization" and fks[0].ondelete == "CASCADE"


def test_user_fks_cascade_so_a_hard_delete_removes_the_rows():
    for model in MODELS:
        fks = list(model.__table__.columns["user_id"].foreign_keys)
        assert len(fks) == 1 and fks[0].column.table.name == "user" and fks[0].ondelete == "CASCADE"


def test_unique_constraints_match_the_contract():
    ev = {u.name: [c.name for c in u.columns] for u in MkaAutomationEvent.__table__.constraints if isinstance(u, sa.UniqueConstraint)}
    sl = {u.name: [c.name for c in u.columns] for u in MkaAutomationSendLog.__table__.constraints if isinstance(u, sa.UniqueConstraint)}
    assert list(ev.values()) == [["org_id", "delivery_id"]]
    assert list(sl.values()) == [["org_id", "kind", "dedupe_key"]]


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
    MkaAutomationEvent.metadata.create_all(other, tables=[m.__table__ for m in MODELS])
    _run(engine, "upgrade")
    assert _state(engine) == _state(other)
    other.dispose()


def test_upgrade_after_create_all_bootstrap(engine):
    MkaAutomationEvent.metadata.create_all(engine, tables=[m.__table__ for m in MODELS])
    before = _state(engine)
    _run(engine, "upgrade")
    assert _state(engine) == before


def test_upgrade_adds_only_missing_index(engine):
    MkaAutomationEvent.metadata.create_all(engine, tables=[m.__table__ for m in MODELS])
    with engine.begin() as conn:
        conn.execute(sa.text("DROP INDEX ix_mka_automation_send_log_cap"))
    _run(engine, "upgrade")
    assert "ix_mka_automation_send_log_cap" in _state(engine)["mka_automation_send_log"][1]


def test_downgrade_removes_everything_and_repeat_is_noop(engine):
    _run(engine, "upgrade")
    _run(engine, "downgrade")
    assert _state(engine) == {}
    _run(engine, "downgrade")
    assert _state(engine) == {}


def test_unique_constraints_are_enforced_by_the_migrated_schema(engine):
    with engine.begin() as conn:  # parents the FKs reference (SQLite does not enforce FKs, keep it honest anyway)
        conn.execute(sa.text("CREATE TABLE organization (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text('CREATE TABLE "user" (id INTEGER PRIMARY KEY)'))
    _run(engine, "upgrade")
    ins = sa.text(
        "INSERT INTO mka_automation_send_log (org_id, kind, dedupe_key, to_email, intended_email, subject, status, test_mode, created_at) "
        "VALUES (1, 'receipt', 'k', 'a@example.invalid', 'a@example.invalid', 's', 'queued', 0, '2026-01-01')"
    )
    with engine.begin() as conn:
        conn.execute(ins)
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(ins)
    ev = sa.text("INSERT INTO mka_automation_event (org_id, delivery_id, event, status, received_at) VALUES (1, 'd1', 'x', 'received', '2026-01-01')")
    with engine.begin() as conn:
        conn.execute(ev)
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(ev)
    # NULL delivery ids (internal events) never collide
    null_ev = sa.text("INSERT INTO mka_automation_event (org_id, delivery_id, event, status, received_at) VALUES (1, NULL, 'x', 'received', '2026-01-01')")
    with engine.begin() as conn:
        conn.execute(null_ev)
        conn.execute(null_ev)
