"""MKA fork: API-token rights check (same semantics as the compliance API's ``token_may``
so the two can share one helper later).

A token acts only within its configured rights: empty rights are refused, otherwise
``rights[resource][action]`` must be true. Reads need ``users.action_read``; roster
writes / imports / deletes need ``organizations.action_update``.
"""

from fastapi import HTTPException

from src.db.users import APITokenUser

TOKEN_READ = ("users", "action_read")
TOKEN_WRITE = ("organizations", "action_update")


def token_may(token_user: APITokenUser, resource: str, action: str) -> None:
    rights = token_user.rights
    if not rights:
        raise HTTPException(status_code=403, detail="API token has no permissions configured")
    node = rights.get(resource) if isinstance(rights, dict) else getattr(rights, resource, None)
    allowed = node.get(action) if isinstance(node, dict) else getattr(node, action, False)
    if not allowed:
        raise HTTPException(status_code=403, detail=f"API token lacks {resource}.{action}")
