import pytest

from tests.fake import REPORT_URL, FakeSession


@pytest.fixture(autouse=True)
def no_live_services(monkeypatch):
    """Never the live API or the live Commando Center: every request goes to a FakeSession,
    version reports to its REPORT_URL. Tests that need their own session patch it again."""
    monkeypatch.setenv("SUPERTEXT_REPORT_URL", REPORT_URL)
    monkeypatch.delenv("SUPERTEXT_VERSION_REPORTS", raising=False)
    monkeypatch.delenv("SUPERTEXT_API_KEY", raising=False)
    monkeypatch.delenv("SUPERTEXT_REVIEW_URL", raising=False)
    fake = FakeSession()
    monkeypatch.setattr("djangocms_supertext.client.requests.Session", lambda: fake)
    return fake
