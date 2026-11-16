#!/bin/sh
# MKA fork: run Alembic migrations before the API starts. Called from docker/start.sh (one line).
# Never fails the container: errors are logged as MKA_MIGRATE_FAILED (see src/services/mka/schema_migrate.py).
# Opt out with MKA_SKIP_MIGRATIONS=1.
cd /app/api 2>/dev/null || cd "$(dirname "$0")/.." || exit 0
echo "MKA_MIGRATE starting"
uv run python -m src.services.mka.schema_migrate || echo "MKA_MIGRATE_FAILED migrate process exited non-zero"
exit 0
