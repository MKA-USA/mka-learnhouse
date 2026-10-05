"""MKA fork: the backfill entry point wires args to recompute_users."""

from unittest.mock import AsyncMock, patch

from src.services.mka import backfill


def test_main_default(capsys):
    with patch.object(backfill, "run", new=AsyncMock(return_value={"processed": 1})) as run:
        assert backfill.main([]) == 0
    run.assert_awaited_once_with(org_id=None, dry_run=False)
    assert '"processed": 1' in capsys.readouterr().out


def test_main_flags():
    with patch.object(backfill, "run", new=AsyncMock(return_value={})) as run:
        backfill.main(["--org-id", "3", "--dry-run"])
    run.assert_awaited_once_with(org_id=3, dry_run=True)
