"""MKA fork: one-off purge + re-index of activities whose content contains audience sections.

Before the ``rag_audience`` guard, audience-restricted text was embedded into the shared per-course RAG index. Run this once per
environment after deploying the guard. Per affected activity it (1) DELETES its index rows (fail closed: restricted chunks are
gone even if the re-index later fails or the org no longer uses AI search) and (2) re-indexes it through the normal pipeline,
which now excludes audience sections. Idempotent; safe to re-run. Activities without audience nodes are not touched.

    cd apps/api && uv run python -m src.services.mka.rag_audience_reindex            # purge + re-index inline
    ... --dry-run                                                                     # list affected activities only
    ... --no-reindex                                                                  # purge only
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import cast, delete, String
from sqlmodel import select

from src.services.mka.rag_audience import contains_audience

logger = logging.getLogger(__name__)


async def affected_activity_ids(db) -> list[int]:
    """Ids of activities whose stored content contains an ``mkaAudience`` node (SQL prefilter, exact check in Python)."""
    from src.db.courses.activities import Activity

    rows = (await db.execute(
        select(Activity.id, Activity.content).where(cast(Activity.content, String).like('%mkaAudience%'))
    )).all()
    return sorted(activity_id for activity_id, content in rows if contains_audience(content))


async def run(*, dry_run: bool = False, reindex: bool = True) -> dict:
    from src.core.events.database import _async_session_factory
    from src.db.course_embeddings import CourseEmbedding
    from src.services.ai.rag import pipeline
    from src.services.ai.rag.types import ContentRef

    async with _async_session_factory() as db:
        ids = await affected_activity_ids(db)
        if dry_run or not ids:
            return {"activities": len(ids), "purged": False, "reindexed": 0}
        await db.execute(delete(CourseEmbedding).where(CourseEmbedding.activity_id.in_(ids)))  # type: ignore[union-attr]
        await db.commit()

    reindexed = 0
    if reindex:
        for activity_id in ids:
            try:
                await pipeline.run(ContentRef.activity(activity_id), transcribe=False)
                reindexed += 1
            except Exception:  # noqa: BLE001 - rows are already purged; keep going, the scheduler/next run retries
                logger.exception("re-index failed for activity %s", activity_id)
    return {"activities": len(ids), "purged": True, "reindexed": reindexed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-reindex", action="store_true")
    args = parser.parse_args()
    print(asyncio.run(run(dry_run=args.dry_run, reindex=not args.no_reindex)))


if __name__ == "__main__":
    main()
