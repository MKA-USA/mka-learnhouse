#!/usr/bin/env bash
# Run a command with LH_API_TOKEN from the PROD keychain item. The token is passed only through the child's environment;
# it is never printed or logged. LH_TOKEN_TARGET=prod makes the provisioner refuse to use it for any other target
# (and refuse a dev token for --target prod). Used by `bun run lh:prod`.
set -u
set +x
if [ "$#" -eq 0 ]; then echo "usage: with-lh-token-prod.sh <command> [args...]" >&2; exit 2; fi
LH_API_TOKEN="$(security find-generic-password -s MKA_LH_PROD_API_TOKEN -w 2>/dev/null)" || {
  echo "with-lh-token-prod: keychain item MKA_LH_PROD_API_TOKEN not found" >&2; exit 1; }
[ -n "$LH_API_TOKEN" ] || { echo "with-lh-token-prod: empty token" >&2; exit 1; }
export LH_API_TOKEN
export LH_TOKEN_TARGET=prod
exec "$@"
