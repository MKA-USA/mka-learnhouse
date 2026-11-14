#!/usr/bin/env bash
# MKA fork: simulate a production-like upgrade and assert zero schema drift afterwards.
#
#   scripts/mka/migration-sim.sh <base-ref> [head-ref]    (head defaults to the current checkout)
#
# Needs a Postgres reachable at LEARNHOUSE_SQL_CONNECTION_STRING (an EMPTY database; it is wiped first).
# 1. checks out <base-ref>'s apps/api, builds its schema the way dev/prod got there (create_all) and stamps its heads
# 2. runs the CURRENT code's mka migrate logic (what docker/start.sh runs)
# 3. runs the drift comparator; exit 1 on any drift / not at head.
set -euo pipefail

BASE_REF="${1:?usage: migration-sim.sh <base-ref> [head-ref]}"
HEAD_REF="${2:-}"
ROOT="$(git rev-parse --show-toplevel)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
: "${LEARNHOUSE_SQL_CONNECTION_STRING:?set LEARNHOUSE_SQL_CONNECTION_STRING}"
export LEARNHOUSE_AUTH_JWT_SECRET_KEY="${LEARNHOUSE_AUTH_JWT_SECRET_KEY:-sim-secret-key-for-migration-sim-32chars!}"
export LEARNHOUSE_DOMAIN="${LEARNHOUSE_DOMAIN:-localhost}"

echo "== wipe database"
(cd "$ROOT/apps/api" && uv sync --quiet && uv run python - <<'PY'
import os, sqlalchemy as sa
e = sa.create_engine(os.environ["LEARNHOUSE_SQL_CONNECTION_STRING"].replace("+asyncpg", ""), isolation_level="AUTOCOMMIT")
with e.connect() as c:
    c.execute(sa.text("DROP SCHEMA public CASCADE")); c.execute(sa.text("CREATE SCHEMA public"))
PY
)

echo "== build BASE schema from $BASE_REF (create_all + stamp heads)"
mkdir -p "$WORK/base"
git -C "$ROOT" archive "$BASE_REF" apps/api | tar -x -C "$WORK/base"
(
  cd "$WORK/base/apps/api"
  uv sync --quiet
  uv run python - <<'PY'
import importlib, os, sqlalchemy as sa
from sqlmodel import SQLModel
for dirpath, _d, files in os.walk("src/db"):
    rel = os.path.relpath(dirpath, "src/db")
    base = "src.db" if rel == "." else "src.db." + rel.replace(os.sep, ".")
    for f in files:
        if f.endswith(".py") and f != "__init__.py":
            importlib.import_module(f"{base}.{f[:-3]}")
url = os.environ["LEARNHOUSE_SQL_CONNECTION_STRING"].replace("+asyncpg", "")
e = sa.create_engine(url)
with e.begin() as c:
    try: c.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as exc: print("pgvector unavailable:", exc)
SQLModel.metadata.create_all(e)
print("base create_all done:", len(SQLModel.metadata.tables), "tables")
PY
  uv run alembic stamp heads
)

if [ -n "$HEAD_REF" ]; then
  mkdir -p "$WORK/head"
  git -C "$ROOT" archive "$HEAD_REF" apps/api | tar -x -C "$WORK/head"
  HEAD_API="$WORK/head/apps/api"
else
  HEAD_API="$ROOT/apps/api"
fi

cd "$HEAD_API"
uv sync --quiet

echo "== drift BEFORE migrate (HEAD code vs BASE-built DB)"
uv run python - <<'PY' || true
import os, sqlalchemy as sa
from src.services.mka import schema_drift as d
d.load_models()
e = sa.create_engine(os.environ["LEARNHOUSE_SQL_CONNECTION_STRING"].replace("+asyncpg", ""))
with e.connect() as c:
    dr = d.compute_drift(c)
    print("BEFORE: missing =", dr.count, "|", dr.describe(), "| alembic_at_head =", d.alembic_at_head(c))
PY

echo "== run mka migrate (HEAD code)"
uv run python -m src.services.mka.schema_migrate | tee "$WORK/migrate.log"
if grep -q MKA_MIGRATE_FAILED "$WORK/migrate.log"; then echo "FAIL: migration failed"; exit 1; fi

echo "== drift AFTER migrate"
uv run python - <<'PY'
import os, sys, sqlalchemy as sa
from src.services.mka import schema_drift as d
d.load_models()
e = sa.create_engine(os.environ["LEARNHOUSE_SQL_CONNECTION_STRING"].replace("+asyncpg", ""))
with e.connect() as c:
    dr = d.compute_drift(c)
    head = d.alembic_at_head(c)
print("AFTER: missing =", dr.count, "|", dr.describe(), "| alembic_at_head =", head)
sys.exit(0 if dr.ok and head else 1)
PY
echo "OK: zero drift"
