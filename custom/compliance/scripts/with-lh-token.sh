#!/usr/bin/env bash
# Run a command with LH_API_TOKEN from the macOS keychain. The token is passed
# only through the child's environment; it is never printed or logged.
set -u
set +x
if [ "$#" -eq 0 ]; then echo "usage: with-lh-token.sh <command> [args...]" >&2; exit 2; fi
LH_API_TOKEN="$(security find-generic-password -s MKA_LH_DEV_API_TOKEN -w 2>/dev/null)" || {
  echo "with-lh-token: keychain item MKA_LH_DEV_API_TOKEN not found" >&2; exit 1; }
[ -n "$LH_API_TOKEN" ] || { echo "with-lh-token: empty token" >&2; exit 1; }
export LH_API_TOKEN
exec "$@"
