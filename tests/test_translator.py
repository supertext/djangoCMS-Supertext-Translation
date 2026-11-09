"""End to end on SQLite: a django CMS page with Text plugins is translated through a fake Supertext API."""

import pytest
from cms.api import add_plugin, create_page
from cms.models import PageContent
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from djangocms_supertext import conf, translator
from djangocms_supertext.models import Translation
from tests.fake import FakeSession

pytestmark = pytest.mark.django_db

BODY = '<h2>From Bern</h2><p>Made by hand in <strong>Bern</strong>. See <a href="https://www.supertext.com">our website</a>.</p>'


@pytest.fixture
def page():
    page = create_page("Swiss chocolate", "page.html", "en", meta_description="Handmade pralines.", menu_title="Chocolate")
    placeholders = page.get_admin_content("en").rescan_placeholders()
    add_plugin(placeholders["content"], "TextPlugin", "en", body=BODY)
    add_plugin(placeholders["sidebar"], "TextPlugin", "en", body="<p>Opening hours</p>")
    return page


@pytest.fixture
def session(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr("djangocms_supertext.client.requests.Session", lambda: session)
    return session


def options():
    return conf.load({"API_KEY": "test-key", "API_URL": "https://api.test/v1/", "LANGUAGES": {"de-ch": {"politeness": "more"}}, "POLL_INTERVAL": 0})


def texts(page, language):
    from djangocms_text.models import Text

    content = PageContent.admin_manager.get(page=page, language=language)
    bodies = {}
    for placeholder in content.get_placeholders():
        bodies[placeholder.slot] = [t.body for t in Text.objects.filter(placeholder=placeholder, language=language).order_by("position")]
    return content, bodies


def test_creates_translations_with_markup_and_plugins(page, session):
    client = options().client(session=session, sleep=lambda s: None)
    results = translator.translate_page(page, "en", ["de-ch", "fr-ch"], options=options(), client=client)

    assert [(r.language, r.status, r.created) for r in results] == [("de-ch", "translated", True), ("fr-ch", "translated", True)]
    content, bodies = texts(page, "de-ch")
    assert content.title == "[de-CH] Swiss chocolate"
    assert content.menu_title == "[de-CH] Chocolate"
    assert content.meta_description == "[de-CH] Handmade pralines."
    assert page.get_slug("de-ch") == "de-ch-swiss-chocolate"
    assert content.template == "page.html"
    assert bodies["content"] == ['<h2>[de-CH] From Bern</h2><p>[de-CH] Made by hand in <strong>[de-CH] Bern</strong>[de-CH] . See <a href="https://www.supertext.com">[de-CH] our website</a>[de-CH] .</p>']
    assert bodies["sidebar"] == ["<p>[de-CH] Opening hours</p>"]
    # The source is untouched
    assert texts(page, "en")[1]["content"] == [BODY]
    # One request per language, with tone and the primary source subtag
    posts = [c for c in session.calls if c["method"] == "POST"]
    assert [p["data"] for p in posts] == [
        {"target_lang": "de-CH", "source_lang": "en", "politeness": "more"},
        {"target_lang": "fr-CH", "source_lang": "en"},
    ]
    assert Translation.objects.filter(page=page, status="translated").count() == 2


def test_skips_existing_languages_unless_overwrite(page, session):
    client = options().client(session=session, sleep=lambda s: None)
    translator.translate_page(page, "en", ["de-ch"], options=options(), client=client)
    content, _ = texts(page, "de-ch")
    content.title = "Edited by hand"
    content.save()

    results = translator.translate_page(page, "en", ["de-ch"], options=options(), client=client)
    assert results[0].status == "skipped"
    assert texts(page, "de-ch")[0].title == "Edited by hand"

    results = translator.translate_page(page, "en", ["de-ch"], overwrite=True, options=options(), client=client)
    assert results[0].status == "translated" and not results[0].created
    content, bodies = texts(page, "de-ch")
    assert content.title == "[de-CH] Swiss chocolate"
    assert len(bodies["content"]) == 1 and len(bodies["sidebar"]) == 1  # replaced, not duplicated


def test_errors_are_reported_per_language(page):
    session = FakeSession(fail_status=500)
    client = options().client(session=session, sleep=lambda s: None)
    results = translator.translate_page(page, "en", ["de-ch"], options=options(), client=client)
    assert results[0].status == "error" and "unavailable" in results[0].message
    assert not PageContent.admin_manager.filter(page=page, language="de-ch").exists()


def test_unmapped_language_is_not_sent(page, session):
    # "en-ie" has no Supertext code and no default (en-GB? en-US?): reported for that language, nothing sent for it.
    client = options().client(session=session, sleep=lambda s: None)
    results = translator.translate_page(page, "en", ["en-ie", "fr-ch"], options=options(), client=client)
    assert [(r.language, r.status, r.code) for r in results] == [("en-ie", "error", "unsupported_language"), ("fr-ch", "translated", "")]
    assert "The language en-ie has no Supertext language yet" in results[0].message
    assert "Settings and connection → Languages" in results[0].message
    assert [c["data"]["target_lang"] for c in session.calls if c["method"] == "POST"] == ["fr-CH"]


def test_language_chosen_on_the_settings_page_is_used(page, session):
    from djangocms_supertext.models import LanguageSetting

    LanguageSetting.objects.create(language="fr-ch", supertext_code="fr-FR", politeness="more")
    opts = options()
    results = translator.translate_page(page, "en", ["fr-ch"], options=opts, client=opts.client(session=session, sleep=lambda s: None))
    assert results[0].status == "translated"
    posts = [c["data"] for c in session.calls if c["method"] == "POST"]
    assert [(d["target_lang"], d.get("politeness")) for d in posts] == [("fr-FR", "more")]


def test_translation_review_language_goes_through_the_review_service(page, session):
    from djangocms_supertext.models import LanguageSetting

    LanguageSetting.objects.create(language="de-ch", review=True)
    opts = conf.load({"API_KEY": "test-key", "API_URL": "https://api.test/v1/", "REVIEW_URL": "https://review.test/v1/", "POLL_INTERVAL": 0})
    results = translator.translate_page(page, "en", ["de-ch", "fr-ch"], options=opts, client=opts.client(session=session, sleep=lambda s: None))
    assert [r.status for r in results] == ["translated", "translated"]
    by_host = [(c["method"], c["url"].split("/v1/")[0], c["url"].split("/v1/")[1]) for c in session.calls]
    review = [(m, p) for m, host, p in by_host if host == "https://review.test"]
    direct = [(m, p) for m, host, p in by_host if host == "https://api.test"]
    assert [m for m, _ in review] == ["POST", "GET", "GET", "DELETE"] and [m for m, _ in direct] == ["POST", "GET", "GET", "DELETE"]
    assert review[1][1].endswith("/status") and review[2][1].endswith("/translation")
    posts = {c["url"].split("/v1/")[0]: c["data"]["target_lang"] for c in session.calls if c["method"] == "POST"}
    assert posts == {"https://review.test": "de-CH", "https://api.test": "fr-CH"}


def test_empty_review_url_turns_review_off(page, session):
    from djangocms_supertext.models import LanguageSetting

    LanguageSetting.objects.create(language="de-ch", review=True)
    opts = conf.load({"API_KEY": "test-key", "API_URL": "https://api.test/v1/", "REVIEW_URL": "", "POLL_INTERVAL": 0})
    translator.translate_page(page, "en", ["de-ch"], options=opts, client=opts.client(session=session, sleep=lambda s: None))
    assert session.calls and all(c["url"].startswith("https://api.test/v1/") for c in session.calls)


def test_settings_page_saves_translation_review(session, client):
    from djangocms_supertext.models import LanguageSetting

    client.force_login(User.objects.create_superuser("admin", "admin@example.com", "pw-123456789"))
    url = reverse("admin:djangocms_supertext_settings")
    response = client.get(url)
    assert b'name="review-de-ch"' in response.content and b"Translation review" in response.content
    client.post(url, {"action": "languages", "target-de-ch": "de-CH", "review-de-ch": "1"})
    assert LanguageSetting.objects.get(language="de-ch").review is True
    assert LanguageSetting.objects.get(language="fr-ch").review is False
    response = client.get(url)
    assert b'name="review-de-ch" value="1" data-supertext-review checked' in response.content


def test_politeness_without_support_is_reported(page, session):
    opts = conf.load({"API_KEY": "test-key", "API_URL": "https://api.test/v1/", "LANGUAGES": {"en-us": {"politeness": "more"}}, "POLL_INTERVAL": 0})
    results = translator.translate_page(page, "en", ["en-us"], options=opts, client=opts.client(session=session, sleep=lambda s: None))
    assert results[0].code == "unsupported_feature" and "no formal or informal tone" in results[0].message
    assert not [c for c in session.calls if c["method"] == "POST"]


def test_describe(page, session):
    client = options().client(session=session, sleep=lambda s: None)
    translator.translate_page(page, "en", ["de-ch"], options=options(), client=client)
    languages = {lang["code"]: lang for lang in translator.describe(page)}
    assert languages["en"]["exists"] and languages["de-ch"]["exists"] and not languages["fr-ch"]["exists"]
    assert languages["de-ch"]["last_translation"] is not None


def editor(perm=True):
    user = User.objects.create_user("editor", "editor@example.com", "pw-123456789", is_staff=True)
    codenames = ["view_page", "change_page", "add_pagecontent", "change_pagecontent", "view_pagecontent"]
    perms = list(Permission.objects.filter(content_type__app_label="cms", codename__in=codenames))
    perms += list(Permission.objects.filter(content_type__app_label="djangocms_text"))
    if perm:
        perms += list(Permission.objects.filter(codename="translate"))
    user.user_permissions.set(perms)
    return user


def test_translate_dialog(page, session, client):
    client.force_login(editor())
    url = reverse("admin:djangocms_supertext_translate", args=[page.pk])
    response = client.get(url + "?language=en")
    assert response.status_code == 200
    assert b"Deutsch (Schweiz)" in response.content and b'value="de-ch"' in response.content

    response = client.post(url, {"source": "en", "targets": ["de-ch"]})
    assert response.status_code == 200
    assert b"translation created" in response.content
    assert PageContent.admin_manager.filter(page=page, language="de-ch").exists()
    assert Translation.objects.get(target_language="de-ch").user.username == "editor"


def test_translate_dialog_needs_permission(page, client):
    client.force_login(editor(perm=False))
    response = client.get(reverse("admin:djangocms_supertext_translate", args=[page.pk]))
    assert response.status_code == 403


def test_settings_page(session, client):
    admin = User.objects.create_superuser("admin", "admin@example.com", "pw-123456789")
    client.force_login(admin)
    url = reverse("admin:djangocms_supertext_settings")
    response = client.get(url)
    assert response.status_code == 200 and b"https://api.test/v1/" in response.content and b"de-CH" in response.content
    from djangocms_supertext import __version__

    release = f"https://github.com/Supertext/djangoCMS-Supertext-Translation/releases/tag/v{__version__}"
    assert b"Plugin version" in response.content and f">{__version__}</a>".encode() in response.content
    assert f'href="{release}" target="_blank" rel="noopener"'.encode() in response.content
    response = client.post(url, follow=True)
    assert b"API key checked: the connection to Supertext works." in response.content
    assert b'data-supertext-key-check="ok"' in response.content


def test_settings_page_version_without_release(session, client, monkeypatch):
    from djangocms_supertext import admin as st_admin

    monkeypatch.setattr(st_admin, "__version__", "0.2.0.dev1")
    client.force_login(User.objects.create_superuser("admin", "admin@example.com", "pw-123456789"))
    response = client.get(reverse("admin:djangocms_supertext_settings"))
    assert b"0.2.0.dev1" in response.content and b"releases/tag" not in response.content
