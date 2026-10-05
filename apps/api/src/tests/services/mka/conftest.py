import pytest


@pytest.fixture(autouse=True)
def _google_only_domains(monkeypatch):
    """Deployment config under test: both officeholder domains are Google-only (hd enforced)."""
    monkeypatch.setenv("MKA_GOOGLE_ONLY_DOMAINS", "mkausa.org,atfalusa.org")
