"""Text loaders for the moderation scheduler.

A loader is ``async (db_session) -> str``. Only plain text is ever returned:
no files, images or quiz option ids. Forum loaders close over the already
saved strings; assignment/profile loaders read fresh rows in the task's own
session so the request session is never shared with the background task.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

TextLoader = Callable[[AsyncSession], Awaitable[str]]

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_PREFIXED_UUID_RE = re.compile(r"^[a-z_]+_[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-")
_MAX_TASK_CHARS = 4000


def forum_text(*parts: str | None) -> TextLoader:
    """Loader for discussion titles/bodies and comments (tiptap JSON or plain)."""

    async def _load(_session: AsyncSession) -> str:
        from src.services.communities.moderation import parse_content_for_moderation

        chunks = [parse_content_for_moderation(p) for p in parts if p]
        return "\n".join(c.strip() for c in chunks if c and c.strip())

    return _load


def profile_text(bio: str | None, first_name: str | None, last_name: str | None) -> TextLoader:
    """Loader for profile free-text fields (bio, first and last name only)."""

    async def _load(_session: AsyncSession) -> str:
        name = " ".join(p.strip() for p in (first_name, last_name) if p and p.strip())
        return "\n".join(p.strip() for p in (name, bio) if p and p.strip())

    return _load


def _is_id_like(value: str) -> bool:
    v = value.strip()
    return bool(_UUID_RE.match(v) or _PREFIXED_UUID_RE.match(v))


def _collect_strings(value: Any, out: list[str], depth: int = 0) -> None:
    """Collect free-text strings from an arbitrary JSON value (CUSTOM tasks)."""
    if depth > 6:
        return
    if isinstance(value, str):
        if value.strip() and not _is_id_like(value):
            out.append(value.strip())
    elif isinstance(value, dict):
        for k, v in value.items():
            # Skip anything that looks like a file/attachment reference.
            if isinstance(k, str) and k.lower() in {"file", "files", "url", "uploads", "attachment", "attachments"}:
                continue
            _collect_strings(v, out, depth + 1)
    elif isinstance(value, list):
        for v in value:
            _collect_strings(v, out, depth + 1)


def task_text(assignment_type: str, task_submission: dict | None) -> str:
    """Free text of ONE task submission. Quiz option ids and files yield ''."""
    data = task_submission or {}
    kind = str(getattr(assignment_type, "value", assignment_type))

    if kind == "SHORT_ANSWER":
        answer = data.get("answer")
        return answer.strip() if isinstance(answer, str) else ""

    if kind == "CODE":
        code = data.get("source_code")
        return code.strip() if isinstance(code, str) else ""

    if kind == "FORM":
        answers = []
        for sub in data.get("submissions") or []:
            if isinstance(sub, dict) and isinstance(sub.get("answer"), str) and sub["answer"].strip():
                answers.append(sub["answer"].strip())
        return "\n".join(answers)

    if kind == "CUSTOM":
        out: list[str] = []
        _collect_strings(data, out)
        return "\n".join(out)

    # QUIZ (option uuids), FILE_SUBMISSION, NUMBER_ANSWER, OTHER: never text.
    return ""


def assignment_submission_text(user_id: int, assignment_id: int) -> TextLoader:
    """Loader: all of the user's saved task answers for one assignment."""

    async def _load(session: AsyncSession) -> str:
        from src.db.courses.assignments import AssignmentTask, AssignmentTaskSubmission

        rows = (
            await session.execute(
                select(AssignmentTaskSubmission, AssignmentTask)
                .join(AssignmentTask, col(AssignmentTask.id) == col(AssignmentTaskSubmission.assignment_task_id))
                .where(
                    AssignmentTaskSubmission.user_id == user_id,
                    AssignmentTask.assignment_id == assignment_id,
                )
                .order_by(col(AssignmentTask.id))
            )
        ).all()

        chunks: list[str] = []
        for submission, _task in rows:
            text = task_text(submission.assignment_type, submission.task_submission)
            if text:
                chunks.append(text[:_MAX_TASK_CHARS])
        return "\n\n".join(chunks)

    return _load
