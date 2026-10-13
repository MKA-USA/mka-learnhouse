"""MKA fork: the audience RAG purge migration deletes only matching activities' rows, is idempotent and tolerates missing tables."""

import importlib.util
import json
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = Path(__file__).resolve().parents[4] / "migrations" / "versions" / "mka_20261013_purge_audience_rag.py"


def _load():
    spec = importlib.util.spec_from_file_location("mka_purge_mig", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _upgrade(conn):
    mod = _load()
    with Operations.context(MigrationContext.configure(conn)):
        mod.upgrade()
        return mod


def test_chain_points_at_merge_head():
    mod = _load()
    assert mod.down_revision == "mka_20261011_merge_upstream"
    assert mod.revision == "mka_20261013_purge_audience_rag"


def test_purges_only_matching_rows_and_is_idempotent():
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(sa.text("CREATE TABLE activity (id INTEGER PRIMARY KEY, content JSON)"))
        conn.execute(sa.text("CREATE TABLE course_embedding (id INTEGER PRIMARY KEY, activity_id INTEGER, course_id INTEGER)"))
        aud = json.dumps({"type": "doc", "content": [{"type": "mkaAudience", "content": []}]})
        plain = json.dumps({"type": "doc", "content": []})
        conn.execute(sa.text("INSERT INTO activity VALUES (1, :a), (2, :p)"), {"a": aud, "p": plain})
        conn.execute(sa.text(
            "INSERT INTO course_embedding (id, activity_id, course_id) VALUES (1,1,9),(2,1,9),(3,2,9),(4,NULL,9)"
        ))
        for _ in range(2):  # second run changes nothing
            _upgrade(conn)
            ids = [r[0] for r in conn.execute(sa.text("SELECT id FROM course_embedding ORDER BY id"))]
            assert ids == [3, 4]
    eng.dispose()


def test_noop_without_tables_or_columns():
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        _upgrade(conn)  # no tables at all
        conn.execute(sa.text("CREATE TABLE activity (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE course_embedding (id INTEGER PRIMARY KEY)"))
        _upgrade(conn)  # tables without the expected columns
    eng.dispose()
