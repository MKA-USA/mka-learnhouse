#!/bin/sh
# Reads newline-separated paths on stdin; exits 1 and explains if any are forbidden.
# Shared by .githooks/pre-commit (staged adds) and .github/workflows/secret-scan.yaml (PR/push diff).
# Secrets belong only in Coolify server env vars, never in git. See docs/security/secrets.md.
bad=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  base=${f##*/}
  reason=""
  case "$base" in
    .env.example|.env.sample|.env.template) ;;
    .env|.env.*) reason="environment file" ;;
    *.pem|*.key|*.p12|*.pfx|id_rsa*|id_ed25519*) reason="private key / certificate material" ;;
    .tinyb) reason="Tinybird credentials file" ;;
    DEVLOG.md|DEVLOG.raw.md) reason="local dev log (may contain pasted secrets)" ;;
    *.jsonl) reason="session transcript" ;;
    *.pyc) reason="Python bytecode cache" ;;
  esac
  if [ -z "$reason" ]; then
    case "/$f" in
      # .claude/skills/ and .qwen/skills/ are tracked on purpose; everything else in these dirs is local state.
      */.claude/skills/*|*/.qwen/skills/*) ;;
      */__pycache__/*) reason="Python bytecode cache" ;;
      */.hermes/*|*/.kiro/*|*/.serena/*|*/.considered/*|*/.agents/*|*/.qwen/*|*/.claude/*) reason="local agent state / session data" ;;
    esac
  fi
  if [ -n "$reason" ]; then
    echo "BLOCKED: $f ($reason)" >&2
    bad=1
  fi
done
if [ "$bad" -ne 0 ]; then
  echo "" >&2
  echo "Secrets and local agent state must not be committed to this public repo." >&2
  echo "Real secrets live only in Coolify env vars per environment; .env.example holds names + placeholders." >&2
  echo "See docs/security/secrets.md. If this is a deliberate non-secret file, ask for a reviewed allowlist change." >&2
  exit 1
fi
exit 0
