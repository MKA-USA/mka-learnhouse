#!/usr/bin/env bash
# Throwaway local stack for the MKA Audience e2e (real API + real web, no mock layer).
#
#   apps/e2e/mka/stack.sh up [--rebuild]   start Postgres + Redis (Docker), API, web; write the stack JSON
#   apps/e2e/mka/stack.sh down [--purge]   stop everything WE started (--purge also removes DB/Redis containers)
#   apps/e2e/mka/stack.sh status           print what is running
#   apps/e2e/mka/stack.sh reset-ratelimit  clear the login rate limit keys (30 logins / 5 min / IP)
#
# Non-default ports on purpose (other sessions run servers on :3000/:5432/:5433...). Override with env:
#   MKA_E2E_PG_PORT (5443)  MKA_E2E_REDIS_PORT (6389)  MKA_E2E_API_PORT (8043)  MKA_E2E_WEB_PORT (3043)
#
# Safety: `down` only stops PIDs recorded in $STATE_DIR (ours) and the two containers named below.
# NEXT_PUBLIC_MKA_AUDIENCE_MOCK is deliberately never set; the audience flag is on.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
STATE_DIR="${MKA_E2E_STATE_DIR:-/private/tmp/claude-501/mka-e2e}"
STACK_JSON="${MKA_E2E_STACK_JSON:-/private/tmp/claude-501/mka-e2e-stack.json}"

PG_PORT="${MKA_E2E_PG_PORT:-5443}"
REDIS_PORT="${MKA_E2E_REDIS_PORT:-6389}"
API_PORT="${MKA_E2E_API_PORT:-8043}"
WEB_PORT="${MKA_E2E_WEB_PORT:-3043}"
PG_NAME="mka-audience-e2e-pg"
REDIS_NAME="mka-audience-e2e-redis"
ADMIN_EMAIL="${MKA_E2E_ADMIN_EMAIL:-admin@e2e-tests.com}"
ORG_SLUG="default"

API_URL="http://localhost:${API_PORT}"
WEB_URL="http://localhost:${WEB_PORT}"

mkdir -p "$STATE_DIR"

secret() { python3 -c "import secrets;print(secrets.token_urlsafe($1))"; }

load_secrets() {
  local f="$STATE_DIR/secrets.env"
  if [ ! -f "$f" ]; then
    {
      echo "LEARNHOUSE_AUTH_JWT_SECRET_KEY=$(secret 40)"
      echo "COLLAB_INTERNAL_KEY=$(secret 24)"
      echo "LEARNHOUSE_INITIAL_ADMIN_PASSWORD=$(secret 12)Aa1!"
      echo "PG_PASSWORD=$(secret 12)"
    } > "$f"
    chmod 600 "$f"
  fi
  set -a; . "$f"; set +a
}

pid_alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

wait_http() { # url label timeout
  local i=0
  until curl -fsS -o /dev/null "$1" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -gt "$3" ]; then echo "timeout waiting for $2 ($1)" >&2; return 1; fi
    sleep 2
  done
  echo "ready: $2"
}

start_containers() {
  if ! docker ps --format '{{.Names}}' | grep -qx "$PG_NAME"; then
    docker rm -f "$PG_NAME" >/dev/null 2>&1 || true
    docker run -d --name "$PG_NAME" -p "127.0.0.1:${PG_PORT}:5432" \
      -e POSTGRES_USER=learnhouse -e POSTGRES_PASSWORD="$PG_PASSWORD" -e POSTGRES_DB=learnhouse \
      pgvector/pgvector:pg16 >/dev/null
  fi
  if ! docker ps --format '{{.Names}}' | grep -qx "$REDIS_NAME"; then
    docker rm -f "$REDIS_NAME" >/dev/null 2>&1 || true
    docker run -d --name "$REDIS_NAME" -p "127.0.0.1:${REDIS_PORT}:6379" redis:7-alpine >/dev/null
  fi
  local i=0
  until docker exec "$PG_NAME" pg_isready -U learnhouse >/dev/null 2>&1; do
    i=$((i + 1)); [ "$i" -gt 40 ] && { echo "postgres not ready" >&2; exit 1; }; sleep 1
  done
  echo "ready: postgres :${PG_PORT}, redis :${REDIS_PORT}"
}

api_env() {
  export LEARNHOUSE_SQL_CONNECTION_STRING="postgresql+asyncpg://learnhouse:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/learnhouse"
  export LEARNHOUSE_REDIS_CONNECTION_STRING="redis://127.0.0.1:${REDIS_PORT}/0"
  export LEARNHOUSE_DEVELOPMENT_MODE=true
  export LEARNHOUSE_TENANCY=single
  export LEARNHOUSE_DOMAIN="localhost:${WEB_PORT}"
  export LEARNHOUSE_FRONTEND_DOMAIN="localhost:${WEB_PORT}"
  export LEARNHOUSE_ALLOWED_ORIGINS="${WEB_URL},http://127.0.0.1:${WEB_PORT}"
  export LEARNHOUSE_INITIAL_ADMIN_EMAIL="$ADMIN_EMAIL"
  export LEARNHOUSE_INITIAL_ORG_NAME="MKA Audience E2E"
  export LEARNHOUSE_INITIAL_ORG_SLUG="$ORG_SLUG"
  # NOT a Google-only domain: e2e-tests.com users can use password login (the email validator rejects .invalid/.test/.example). Never put mkausa.org here.
  export MKA_GOOGLE_ONLY_DOMAINS=""
}

web_env() {
  export NEXT_PUBLIC_LEARNHOUSE_BACKEND_URL="${API_URL}/"
  export NEXT_PUBLIC_LEARNHOUSE_API_URL="${API_URL}/api/v1/"
  export NEXT_PUBLIC_LEARNHOUSE_DOMAIN="localhost:${WEB_PORT}"
  export NEXT_PUBLIC_LEARNHOUSE_DEFAULT_ORG="$ORG_SLUG"
  export NEXT_PUBLIC_COLLAB_URL="ws://localhost:1"      # collab server is not part of this stack
  export NEXT_PUBLIC_MKA_AUDIENCE_ENABLED=1
  unset NEXT_PUBLIC_MKA_AUDIENCE_MOCK NEXT_PUBLIC_MKA_COMPLIANCE_MOCK || true
  export NEXT_TELEMETRY_DISABLED=1
}

write_json() {
  python3 - "$STACK_JSON" <<PY
import json, sys, os
state = "$STATE_DIR"
def pid(name):
    try: return int(open(os.path.join(state, name + ".pid")).read().strip())
    except Exception: return None
json.dump({
  "webUrl": "$WEB_URL", "apiUrl": "$API_URL", "apiV1": "$API_URL/api/v1",
  "orgSlug": "$ORG_SLUG", "adminEmail": "$ADMIN_EMAIL", "stateDir": "$STATE_DIR",
  "adminPasswordFile": "$STATE_DIR/secrets.env (LEARNHOUSE_INITIAL_ADMIN_PASSWORD)",
  "personasFile": "$STATE_DIR/personas.json",
  "pids": {"api": pid("api"), "web": pid("web")},
  "containers": {"postgres": "$PG_NAME", "redis": "$REDIS_NAME"},
  "ports": {"postgres": $PG_PORT, "redis": $REDIS_PORT, "api": $API_PORT, "web": $WEB_PORT},
  "logs": {"api": "$STATE_DIR/api.log", "web": "$STATE_DIR/web.log"},
  "stop": "apps/e2e/mka/stack.sh down  (in $REPO)",
}, open(sys.argv[1], "w"), indent=2)
PY
}

cmd_up() {
  local rebuild=0; [ "${1:-}" = "--rebuild" ] && rebuild=1
  load_secrets
  start_containers

  if ! pid_alive "$STATE_DIR/api.pid"; then
    ( cd "$REPO/apps/api" && api_env && nohup uv run --with greenlet uvicorn app:app --host 127.0.0.1 --port "$API_PORT" \
        > "$STATE_DIR/api.log" 2>&1 & echo $! > "$STATE_DIR/api.pid" )
  fi
  wait_http "${API_URL}/api/v1/health" "api" 90

  if ! pid_alive "$STATE_DIR/web.pid"; then
    ( cd "$REPO/apps/web" && web_env
      if [ "$rebuild" = 1 ] || [ ! -f .next/BUILD_ID ]; then
        echo "building web (production build, audience flag on, mock unset)..."
        bun run build > "$STATE_DIR/web-build.log" 2>&1 || { tail -30 "$STATE_DIR/web-build.log" >&2; exit 1; }
      fi
      # Run like the production image does (standalone + server-wrapper.js, under node; bun 1.3 hangs on SSR here): the wrapper copies every NEXT_PUBLIC_*
      # variable into /runtime-config.js, which the browser bundle reads. Plain `next start` has no runtime config.
      rm -rf .next/standalone/.next/static .next/standalone/public
      mkdir -p .next/standalone/.next
      cp -R .next/static .next/standalone/.next/static
      cp -R public .next/standalone/public
      cp server-wrapper.js .next/standalone/server-wrapper.js
      cd .next/standalone
      HOSTNAME=localhost PORT="$WEB_PORT" nohup node server-wrapper.js > "$STATE_DIR/web.log" 2>&1 & echo $! > "$STATE_DIR/web.pid" )
  fi
  wait_http "${WEB_URL}/login" "web" 90
  # uv/node wrappers may exit or re-exec: record the PID that actually owns each listening port (ours: we just started it)
  for pair in "api:$API_PORT" "web:$WEB_PORT"; do
    lsof -tiTCP:"${pair#*:}" -sTCP:LISTEN 2>/dev/null | head -1 > "$STATE_DIR/${pair%%:*}.pid" || true
  done
  write_json
  echo "stack up -> $STACK_JSON"
}

kill_tree() { # pid: kill it and its children, only if it is ours
  local pid="$1"
  pkill -P "$pid" 2>/dev/null || true
  kill "$pid" 2>/dev/null || true
}

cmd_down() {
  for n in web api; do
    if pid_alive "$STATE_DIR/$n.pid"; then kill_tree "$(cat "$STATE_DIR/$n.pid")"; echo "stopped $n"; fi
    rm -f "$STATE_DIR/$n.pid"
  done
  # next start spawns a node child that we may have orphaned; free the port only if it is OUR listener
  for port in "$WEB_PORT" "$API_PORT"; do
    local p; p="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1 || true)"
    [ -n "$p" ] && echo "note: port $port still held by pid $p (not ours to kill blindly; check with ps -p $p)"
  done
  if [ "${1:-}" = "--purge" ]; then
    docker rm -f "$PG_NAME" "$REDIS_NAME" >/dev/null 2>&1 || true
    rm -rf "$STATE_DIR" "$STACK_JSON"
    echo "purged containers + state"
  else
    docker stop "$PG_NAME" "$REDIS_NAME" >/dev/null 2>&1 || true
    echo "stopped containers (data kept; 'up' restarts them)"
    rm -f "$STACK_JSON"
  fi
}

cmd_status() {
  for n in api web; do
    if pid_alive "$STATE_DIR/$n.pid"; then echo "$n: up (pid $(cat "$STATE_DIR/$n.pid"))"; else echo "$n: down"; fi
  done
  docker ps --format '{{.Names}} {{.Status}}' | grep -E "^($PG_NAME|$REDIS_NAME) " || echo "containers: down"
  curl -fsS -o /dev/null "${API_URL}/api/v1/health" && echo "api health: ok" || echo "api health: unreachable"
  curl -fsS -o /dev/null "${WEB_URL}/login" && echo "web /login: ok" || echo "web /login: unreachable"
  [ -f "$STACK_JSON" ] && echo "stack json: $STACK_JSON" || echo "stack json: missing"
}

case "${1:-}" in
  up) shift; cmd_up "$@" ;;
  down) shift; load_secrets 2>/dev/null || true; cmd_down "$@" ;;
  status) load_secrets; cmd_status ;;
  reset-ratelimit) # only the rate_limit:* keys (sessions/refresh tokens live in the same Redis)
    docker exec "$REDIS_NAME" sh -c "redis-cli --scan --pattern 'rate_limit:*' | xargs -r redis-cli del" ;;
  *) sed -n 2,12p "${BASH_SOURCE[0]}"; exit 2 ;;
esac
