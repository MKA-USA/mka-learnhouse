"""MKA fork: backfill / recompute identity attributes for existing users.

Fork-only entry point (``cli.py`` is upstream-owned, so it is not extended).
Run inside the API environment::

    uv run python -m src.services.mka.backfill --dry-run
    uv run python -m src.services.mka.backfill --org-id 1
    uv run python -m src.services.mka.backfill --include-non-google   # operator decision

Idempotent: re-running changes nothing and writes no audit rows. By default only
users with ``signup_method == 'google'`` are processed (a password signup must
not pick up officeholder attributes from its address; see spec A6/A7).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Optional

from src.services.mka.attributes import recompute_users


async def run(*, org_id: Optional[int], google_only: bool, dry_run: bool) -> dict:
    from src.core.events.database import _async_session_factory

    async with _async_session_factory() as db:
        return await recompute_users(db, org_id=org_id, google_only=google_only, dry_run=dry_run)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Recompute MKA identity attributes for existing users")
    p.add_argument("--org-id", type=int, default=None, help="Only members of this org")
    p.add_argument("--include-non-google", action="store_true",
                   help="Also process users whose signup_method is not 'google'")
    p.add_argument("--dry-run", action="store_true", help="Compute and report, write nothing")
    args = p.parse_args(argv)
    result = asyncio.run(
        run(org_id=args.org_id, google_only=not args.include_non_google, dry_run=args.dry_run)
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
