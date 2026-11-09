"""Commando Center: version reports, the API key check and the ping endpoint (reporting.py), with a
FakeSession for Supertext and the center (never the live services)."""

import io
import json

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import reverse
from django.utils import translation

from djangocms_supertext import __version__, admin as st_admin, conf, reporting
from djangocms_supertext.models import State
from djangocms_supertext._vendor import plugin_health
from djangocms_supertext._vendor.plugin_health import KeyCheck as ApiKeyCheck
from djangocms_supertext._vendor.supertext import SDK_VERSION

pytestmark = pytest.mark.django_db

PING = "/en/admin/djangocms_supertext/translation/ping/"
CHALLENGE = "abcdefghijklmnop1234"


@pytest.fixture
def admin_client(client):
    client.force_login(User.objects.create_superuser("admin", "admin@example.com", "pw-123456789"))
    return client


def state():
    return json.loads(State.objects.get(key="reporter").value)


def test_settings_page_reports_installed_once(admin_client, no_live_services):
    response = admin_client.get(reverse("admin:djangocms_supertext_settings"))
    assert response.status_code == 200
    assert b"Send version information to Supertext" in response.content and b'data-supertext-reports="on"' in response.content
    assert ("http://testserver" + PING).encode() in response.content
    [report] = no_live_services.reports
    assert report["event"] == "installed"
    assert report["site_url"] == "http://testserver"
    assert report["plugin"] == {"name": "djangoCMS-Supertext-Translation", "version": __version__}
    assert report["system"]["name"] == "django CMS" and report["system"]["version"]
    assert report["runtime"]["name"] == "Python"
    assert report["sdk_version"] == SDK_VERSION
    assert report["api_key_configured"] is True and report["api_key_check"]["status"] == "ok"
    assert report["callback"] == {"url": "http://testserver" + PING}
    assert "test-key" not in json.dumps(report)
    stored = state()
    assert stored["reportedVersions"].startswith(__version__ + "|") and stored["keyCheck"]["status"] == "ok"
    assert "test-key" not in State.objects.get(key="reporter").value

    # Nothing changed: no new report, no new key check.
    calls = len(no_live_services.calls)
    response = admin_client.get(reverse("admin:djangocms_supertext_settings"))
    assert len(no_live_services.reports) == 1 and len(no_live_services.calls) == calls
    assert b'data-supertext-key-check="ok"' in response.content and b"checked " in response.content


def test_state_stored_by_the_sdk_reporter_is_kept(admin_client, no_live_services):
    # Stored by the Supertext SDK 0.1-0.2 reporter (same row, same JSON): no new installed report.
    import platform

    from djangocms_supertext._vendor.supertext.v1 import api_key_fingerprint

    versions = f"{__version__}|{reporting.django_cms_version()}|{platform.python_version()}"
    old = {
        "reportedVersions": versions,
        "reportedKeyStatus": "ok",
        "lastFailureAt": None,
        "keyCheck": {"status": "ok", "checkedAt": "2026-10-01T08:00:00Z", "httpStatus": 200, "errorCode": None, "fingerprint": api_key_fingerprint("test-key")},
    }
    State.objects.create(key="reporter", value=json.dumps(old, separators=(",", ":")))
    response = admin_client.get(reverse("admin:djangocms_supertext_settings"))
    assert b'data-supertext-key-check="ok"' in response.content
    assert no_live_services.reports == [] and state() == old


def test_bundled_plugin_health_and_sdk():
    from pathlib import Path

    vendor = Path(reporting.__file__).parent / "_vendor"
    assert (vendor / "plugin_health" / "VERSION").read_text().strip() == plugin_health.PLUGIN_HEALTH_VERSION
    assert (vendor / "supertext" / "VERSION").read_text().strip() == SDK_VERSION
    assert not hasattr(__import__("djangocms_supertext._vendor.supertext.v1", fromlist=["v1"]), "InstallationReporter")


def test_upgrade_is_reported(admin_client, no_live_services, monkeypatch):
    admin_client.get(reverse("admin:djangocms_supertext_settings"))
    monkeypatch.setattr(reporting, "__version__", "9.9.9")
    admin_client.get(reverse("admin:djangocms_supertext_settings"))
    assert [r["event"] for r in no_live_services.reports] == ["installed", "upgraded"]
    assert no_live_services.reports[1]["plugin"]["version"] == "9.9.9"


@override_settings(SUPERTEXT={"API_KEY": "test-key", "API_URL": "https://api.test/v1/", "VERSION_REPORTS": False})
def test_reports_off(admin_client, client, no_live_services):
    response = admin_client.get(reverse("admin:djangocms_supertext_settings"))
    assert b'data-supertext-reports="off"' in response.content
    assert b"Off (VERSION_REPORTS in the SUPERTEXT setting)" in response.content
    assert no_live_services.reports == []
    assert state()["keyCheck"]["status"] == "ok"  # the key check runs anyway
    assert client.get(PING, {"challenge": CHALLENGE}).status_code == 404


def test_reports_off_by_environment(admin_client, no_live_services, monkeypatch):
    monkeypatch.setenv("SUPERTEXT_VERSION_REPORTS", "0")
    response = admin_client.get(reverse("admin:djangocms_supertext_settings"))
    assert b"Off (SUPERTEXT_VERSION_REPORTS=0)" in response.content and no_live_services.reports == []


def test_ping(client):
    response = client.get(PING, {"challenge": CHALLENGE})  # no login
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json" and response["Cache-Control"] == "no-store"
    assert json.loads(response.content) == {"ok": True, "plugin": "djangoCMS-Supertext-Translation", "challenge": CHALLENGE}
    assert client.get(PING, {"challenge": "<script>"}).status_code == 400
    assert client.get(PING).status_code == 400
    assert client.post(PING, {"challenge": CHALLENGE}).status_code == 405


def test_test_connection_shows_and_reports_a_rejected_key(admin_client, no_live_services):
    admin_client.get(reverse("admin:djangocms_supertext_settings"))  # installed, key ok
    with override_settings(SUPERTEXT={"API_KEY": "wrong", "API_URL": "https://api.test/v1/"}):
        response = admin_client.post(reverse("admin:djangocms_supertext_settings"), follow=True)
    assert b"Supertext rejected the API key." in response.content
    assert f'<a href="{conf.API_KEY_URL}" target="_blank" rel="noopener">supertext.com → Integrations → API</a>'.encode() in response.content
    assert f'<a href="{conf.SIGNUP_URL}" target="_blank" rel="noopener">supertext.com</a>'.encode() in response.content
    assert [r["event"] for r in no_live_services.reports] == ["installed", "api_key_check"]
    assert no_live_services.reports[1]["api_key_check"]["status"] == "invalid"


def test_rejected_key_during_translation_is_reported_once(no_live_services):
    from cms.api import create_page

    from djangocms_supertext import translator

    page = create_page("Hello", "page.html", "en")
    options = conf.load({"API_KEY": "wrong", "API_URL": "https://api.test/v1/", "POLL_INTERVAL": 0, "SITE_URL": "https://www.example.ch"})
    reporting.run("on_request", options)  # installed (the key check says invalid already)
    State.objects.filter(key="reporter").update(value=json.dumps({**state(), "keyCheck": None, "reportedKeyStatus": "ok"}))
    for _ in range(2):
        results = translator.translate_page(page, "en", ["de-ch"], options=options)
        assert results[0].code == "authentication_failure" and results[0].http_status == 401
        reporting.report_translation(results, options)
    assert [r["event"] for r in no_live_services.reports] == ["installed", "api_key_check"]
    assert no_live_services.reports[1]["site_url"] == "https://www.example.ch"
    assert state()["keyCheck"]["status"] == "invalid"


def test_supertext_check_sends_a_check_report(no_live_services):
    stdout = io.StringIO()
    with override_settings(SUPERTEXT={"API_KEY": "test-key", "API_URL": "https://api.test/v1/", "SITE_URL": "https://www.example.ch"}):
        call_command("supertext_check", stdout=stdout)
    out = stdout.getvalue()
    assert "The API key works" in out and "Version report to Supertext: sent" in out
    assert no_live_services.reports[-1]["event"] == "check"
    with override_settings(SUPERTEXT={"API_KEY": "wrong", "API_URL": "https://api.test/v1/", "SITE_URL": "https://www.example.ch"}):
        with pytest.raises(CommandError, match="Supertext rejected the API key"):
            call_command("supertext_check", stdout=io.StringIO())


def test_no_site_url_no_report(no_live_services):
    # Commands without a request: the Django site is still example.com, so nothing is reported; the key is still checked.
    result = reporting.run("on_request", conf.load())
    assert result is not None and result.check.status == "ok" and no_live_services.reports == []


def test_center_failure_never_breaks_and_backs_off(admin_client, monkeypatch, no_live_services):
    monkeypatch.setenv("SUPERTEXT_REPORT_URL", "https://down.test/report")
    response = admin_client.get(reverse("admin:djangocms_supertext_settings"))
    assert response.status_code == 200
    assert state()["lastFailureAt"] and state()["reportedVersions"] is None


def test_storage_failure_never_breaks(admin_client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("database down")

    monkeypatch.setattr(reporting, "load_state", broken)
    assert reporting.run("on_request", conf.load()) is None
    assert reporting.last_check() is None
    assert admin_client.get(reverse("admin:djangocms_supertext_settings")).status_code == 200


def test_key_check_messages_in_four_languages():
    check = ApiKeyCheck("error", "2026-10-13T08:00:00Z", 429, None, "f")
    with translation.override("de"):
        assert reporting.check_message(check) == "Der API-Schlüssel konnte nicht geprüft werden: Supertext hat mit einem Fehler geantwortet (429). Die Einstellungen sind gespeichert; prüfen Sie ihn später erneut."
    with translation.override("fr"):
        assert reporting.check_message(ApiKeyCheck("ok", "", 200, None, "f")).startswith("Clé API vérifiée")
    with translation.override("it"):
        html = reporting.check_html(ApiKeyCheck("missing", "", None, None, ""))
    assert html.count('target="_blank" rel="noopener"') == 2 and "supertext.com → Integrations → API</a>" in html


def test_language_rows_preselect_saved_override_or_suggestion():
    options = conf.load({"LANGUAGES": {"en-us": {"politeness": "more"}, "de": {"code": "de-CH"}}}, saved={"fr": {"code": "fr-CH"}})
    it = st_admin._language_row(options, {"code": "it"})
    assert (it["selected"], it["suggested"], it["target"]) == ("it-IT", "it-IT", "it-IT")  # the SDK default
    de = st_admin._language_row(options, {"code": "de"})
    assert (de["selected"], de["override"], de["target"], de["politeness_supported"]) == ("de-CH", "de-CH", "de-CH", True)
    fr = st_admin._language_row(options, {"code": "fr"})
    assert (fr["selected"], fr["override"], fr["suggested"]) == ("fr-CH", "", "")
    ie = st_admin._language_row(options, {"code": "en-ie"})
    assert (ie["selected"], ie["target"]) == ("", None)  # no default: "— choose —"
    assert st_admin._language_row(options, {"code": "en-us"})["politeness_unsupported"] is True


def test_settings_page_shows_a_select_per_language(admin_client):
    languages = {1: [{"code": "en", "name": "English"}, {"code": "en-ie", "name": "English (Ireland)"}]}
    with override_settings(CMS_LANGUAGES=languages, LANGUAGES=[("en", "English"), ("en-ie", "English (Ireland)")]):
        response = admin_client.get(reverse("admin:djangocms_supertext_settings"))
    html = response.content.decode()
    assert '<select name="target-en"' in html and '<select name="target-en-ie"' in html
    assert '<option value="en-US" selected>English (United States) (en-US)</option>' in html  # suggested for en
    assert 'data-supertext-unmapped' in html  # en-ie: no default, must be chosen
    assert '<option value="gsw-u-sd-chzh">' in html


def test_saving_the_languages(admin_client):
    from djangocms_supertext.models import LanguageSetting

    url = reverse("admin:djangocms_supertext_settings")
    data = {"action": "languages", "target-en": "en-GB", "politeness-en": "more", "target-de-ch": "de-CH", "politeness-de-ch": "less", "target-fr-ch": ""}
    response = admin_client.post(url, data)
    assert response.status_code == 302
    rows = {row.language: (row.supertext_code, row.politeness) for row in LanguageSetting.objects.all()}
    # en-GB has no formal/informal; de-ch's politeness is set under LANGUAGES in the SUPERTEXT setting (kept "default").
    assert rows == {"en": ("en-GB", "default"), "de-ch": ("de-CH", "default"), "fr-ch": ("", "default")}
    assert conf.load().target_code("en") == "en-GB" and conf.load().target_code("fr-ch") == "fr-CH"

    response = admin_client.post(url, {"action": "languages", "target-en": "xx-YY"})
    assert response.status_code == 200 and "xx-YY is not a Supertext language." in response.content.decode()
    assert LanguageSetting.objects.get(language="en").supertext_code == "en-GB"  # not changed


def test_target_names_follow_the_admin_language():
    with translation.override("de"):
        labels = dict(st_admin.target_choices())
    assert labels[""] == "— auswählen —"
    assert labels["de-CH"] == "Deutsch (de-CH)" and labels["gsw-u-sd-chzh"].endswith("(gsw-u-sd-chzh)")
    assert dict(st_admin.target_choices())["fr-CH"] == "French (Switzerland) (fr-CH)"
