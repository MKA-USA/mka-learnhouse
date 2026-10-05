"""MKA fork: API-token rights check.

A token acts only within its configured rights: empty rights are refused, otherwise every required
``rights[resource][action]`` must be true. The requirements are mapped onto rights the org API-token UI can
actually grant (it has no ``users`` / ``organizations`` permission): reads need ``courses.action_read`` and
``assignments.action_read`` (the Read-only and Full Access presets both have them); writes (imports, deletes,
roster writes) need ``courses.action_update`` (Full Access only).
"""

from typing import Iterable, Tuple

from fastapi import HTTPException

from src.db.users import APITokenUser

Right = Tuple[str, str]

TOKEN_READ: Tuple[Right, ...] = (("courses", "action_read"), ("assignments", "action_read"))
TOKEN_WRITE: Tuple[Right, ...] = (("courses", "action_update"),)

_PRESET_HINT = {
    TOKEN_READ: "the 'Read-only' or 'Full Access'",
    TOKEN_WRITE: "the 'Full Access'",
}


def _has(rights, resource: str, action: str) -> bool:
    node = rights.get(resource) if isinstance(rights, dict) else getattr(rights, resource, None)
    allowed = node.get(action) if isinstance(node, dict) else getattr(node, action, False)
    return bool(allowed)


def token_may(token_user: APITokenUser, *required: Right) -> None:
    """403 unless the token has rights and every ``(resource, action)`` in ``required`` is granted.

    Accepts the pairs as varargs or as one tuple of pairs (``token_may(user, *TOKEN_READ)``)."""
    rights = token_user.rights
    if not rights:
        raise HTTPException(status_code=403, detail="API token has no permissions configured")
    pairs: Iterable[Right] = required
    missing = [f"{r}.{a}" for r, a in pairs if not _has(rights, r, a)]
    if missing:
        preset = _PRESET_HINT.get(tuple(required), "the 'Full Access'")
        raise HTTPException(
            status_code=403,
            detail=f"API token lacks {', '.join(missing)} — create the token with {preset} permission preset",
        )
