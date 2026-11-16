"""MKA fork: router-test fixtures that only the fork's own ``test_mka_*`` modules use.

Upstream 1.4.5 caps an API token's rights by its creator's *current* role
(``cap_token_rights``), and the shared ``ADMIN_RIGHTS`` test constant has no ``assignments`` bucket, so a
token created by the fixture admin loses ``assignments.*`` and every MKA token test gets a 403. Real Admin
roles do hold it (``services/setup/setup.py``), so the fork's tests give the fixture admin the same bucket.
Upstream's own router tests are untouched (the override only applies to ``test_mka_*`` modules).
"""

import pytest

from src.db.roles import Permission


@pytest.fixture(autouse=True)
def _mka_admin_role_holds_assignments(request, monkeypatch):
    if not request.module.__name__.rsplit(".", 1)[-1].startswith("test_mka_"):
        return
    # pytest imports the shared conftest under its own module name, so find that exact module object.
    shared = next(
        p
        for p in request.config.pluginmanager.get_plugins()
        if str(getattr(p, "__file__", "")).endswith("src/tests/conftest.py")
    )
    full = Permission(action_create=True, action_read=True, action_update=True, action_delete=True)
    monkeypatch.setattr(shared, "ADMIN_RIGHTS", shared.ADMIN_RIGHTS.model_copy(update={"assignments": full}))
