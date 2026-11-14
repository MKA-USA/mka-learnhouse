"""MKA fork: compare the declared SQLModel schema with the live database.

Why this exists: the API only runs ``SQLModel.metadata.create_all`` at startup, which creates missing tables but never
adds a missing column. An upstream migration that adds a column therefore leaves an old database silently short of it
until someone runs Alembic. This module detects exactly that (missing tables, missing columns) and whether the database
is stamped at the Alembic head, so deploys can fail loudly instead of 500-ing at runtime.

Names of tables/columns are returned by ``compute_drift`` for logs and CI, but the public health endpoint exposes only
counts (see ``routers/mka_health.py``).
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Connection
from sqlmodel import SQLModel

API_ROOT = Path(__file__).resolve().parents[3]  # apps/api


@dataclass
class SchemaDrift:
    missing_tables: list[str] = field(default_factory=list)
    missing_columns: list[tuple[str, str]] = field(default_factory=list)  # (table, column)

    @property
    def count(self) -> int:
        return len(self.missing_tables) + len(self.missing_columns)

    @property
    def ok(self) -> bool:
        return self.count == 0

    def describe(self) -> str:
        parts = [f"table:{t}" for t in self.missing_tables]
        parts += [f"column:{t}.{c}" for t, c in self.missing_columns]
        return ", ".join(parts) if parts else "none"


def load_models() -> None:
    """Import every model module so ``SQLModel.metadata`` is complete (mirrors migrations/env.py)."""
    for base_dir, base_module in (("src/db", "src.db"), ("ee/db", "ee.db")):
        root = API_ROOT / base_dir
        if not root.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(root):
            rel = os.path.relpath(dirpath, root)
            module_base = base_module if rel == "." else f"{base_module}.{rel.replace(os.sep, '.')}"
            for name in files:
                if name.endswith(".py") and name != "__init__.py":
                    importlib.import_module(f"{module_base}.{name[:-3]}")


def compute_drift(connection: Connection, metadata=None) -> SchemaDrift:
    """Missing tables/columns of ``metadata`` (default: SQLModel's) in the database behind ``connection``."""
    metadata = metadata if metadata is not None else SQLModel.metadata
    inspector = sa_inspect(connection)
    live_tables = set(inspector.get_table_names())
    drift = SchemaDrift()
    for table in sorted(metadata.tables.values(), key=lambda t: t.name):
        if table.name not in live_tables:
            drift.missing_tables.append(table.name)
            continue
        live_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name not in live_cols:
                drift.missing_columns.append((table.name, col.name))
    return drift


def alembic_head_revisions() -> set[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    return set(ScriptDirectory.from_config(cfg).get_heads())


def alembic_at_head(connection: Connection, heads: set[str] | None = None) -> bool:
    """True when every Alembic head is recorded in ``alembic_version``."""
    heads = heads if heads is not None else alembic_head_revisions()
    if "alembic_version" not in sa_inspect(connection).get_table_names():
        return False
    rows = connection.exec_driver_sql("SELECT version_num FROM alembic_version").fetchall()
    return heads.issubset({r[0] for r in rows})
