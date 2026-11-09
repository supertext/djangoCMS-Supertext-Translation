"""Export for translation / Import translation (XLIFF and HTML), end to end on SQLite."""

import re

import pytest
from cms.api import add_plugin, create_page
from cms.models import PageContent
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from djangocms_supertext import conf, files
from djangocms_supertext._vendor.supertext import files as stfiles
from djangocms_supertext.models import Translation
from tests.test_translator import editor, texts

pytestmark = pytest.mark.django_db

BODY = '<p>Made by hand in <strong>Bern</strong>.</p>'
CODE = re.compile(r"(<(bpt|ept|ph)\b[^>]*>.*?</\2>)", re.S)


@pytest.fixture
def page():
    page = create_page("Swiss chocolate", "page.html", "en", menu_title="Chocolate")
    placeholders = page.get_admin_content("en").rescan_placeholders()
    add_plugin(placeholders["content"], "TextPlugin", "en", body=BODY)
    return page


def options(**languages):
    return conf.load({"API_KEY": "test-key", "API_URL": "https://api.test/v1/", "LANGUAGES": languages, "POLL_INTERVAL": 0})


def translate_xliff(xliff: str, prefix: str = "[FR] ", skip=()) -> str:
    """Adds a <target> to every unit: the source with its inline codes, the words prefixed."""

    def unit(match):
        if match.group(2) in skip:
            return match.group(0)
        parts = CODE.split(match.group(3))
        target, i = "", 0
        while i < len(parts):
            text = parts[i]
            target += (prefix + text) if text.strip() else text
            if i + 1 < len(parts):
                target += parts[i + 1]
            i += 3
        return f"{match.group(1)}<source>{match.group(3)}</source><target>{target}</target>"

    return re.sub(r'(<trans-unit id="([^"]+)"[^>]*>\s*)<source>(.*?)</source>', unit, xliff, flags=re.S)


def key_of(page, field="body"):
    plugin = page.get_admin_content("en").get_placeholders().get(slot="content").get_plugins("en").first()
    return f"plugin.{plugin.pk}.{field}"


def test_reference_round_trip():
    assert files.reference(12, "en", "fr-ch") == "page:12:en:fr-ch"
    assert files.parse_reference("page:12:en:fr-ch") == (12, "en", "fr-ch")
    assert files.parse_reference("page:0:en:fr") is None
    assert files.parse_reference("entry:12:en:fr") is None
    assert files.parse_reference("page:12:en") is None


def test_language_codes_use_the_mapping_and_fall_back():
    opts = options(**{"fr-ch": {"code": "fr-FR"}})
    assert files.language_code(opts, "fr-ch", True) == "fr-FR"
    assert files.language_code(opts, "fr-ch", False) == "fr"
    assert files.language_code(opts, "de-ch", True) == "de-CH"
    assert files.language_code(opts, "en_IE", True) == "en-IE"  # unknown to Supertext: still exported


def test_export_xliff_has_the_collectors_keys(page):
    exported = files.export(page, "en", ["de-ch", "fr-ch"], files.XLIFF, options(**{"fr-ch": {"code": "fr-FR"}}))

    assert exported.name == f"djangocms-page-{page.pk}.xlf"
    assert exported.content_type == "application/x-xliff+xml"
    jobs = stfiles.read(exported.content)
    assert [(j.plugin, j.reference, j.source_language, j.target_language) for j in jobs] == [
        (files.PLUGIN, f"page:{page.pk}:en:de-ch", "en", "de-CH"),
        (files.PLUGIN, f"page:{page.pk}:en:fr-ch", "en", "fr-FR"),
    ]
    assert [u.key for u in jobs[0].units] == ["page.title", "page.menu_title", key_of(page)]


def test_export_html_needs_one_language(page):
    exported = files.export(page, "en", ["fr-ch"], files.HTML, options())
    assert exported.name == f"djangocms-page-{page.pk}-fr-CH.html"
    assert exported.content_type == "text/html; charset=utf-8"
    assert "data-st-id" in exported.content

    with pytest.raises(files.FileError):
        files.export(page, "en", ["fr-ch", "de-ch"], files.HTML, options())


def test_nothing_to_export():
    page = create_page(" ", "page.html", "en")
    PageContent.admin_manager.filter(page=page).update(title="")
    with pytest.raises(files.FileError, match="Nothing to translate"):
        files.export(page, "en", ["fr-ch"], files.XLIFF, options())


def test_import_writes_ok_segments_through_the_api_write_back(page):
    user = editor()
    xliff = translate_xliff(files.export(page, "en", ["fr-ch"], files.XLIFF, options()).content)

    [result] = files.import_file(xliff.encode(), user=user, options=options())

    assert result.error == ""
    assert result.counts == {"ok": 3, "changed": 0, "untranslated": 0, "invalid": 0, "missing": 0}
    assert result.created and result.language == "Français (Suisse)"
    content, bodies = texts(page, "fr-ch")
    assert content.title == "[FR] Swiss chocolate"
    assert content.menu_title == "[FR] Chocolate"
    assert bodies["content"] == ["<p>[FR] Made by hand in <strong>[FR] Bern</strong>[FR] .</p>"]
    assert Translation.objects.get(target_language="fr-ch").message == "XLIFF"


def test_existing_language_only_with_overwrite(page):
    user = editor()
    xliff = translate_xliff(files.export(page, "en", ["fr-ch"], files.XLIFF, options()).content)
    files.import_file(xliff, user=user, options=options())

    [result] = files.import_file(xliff, user=user, options=options())
    assert result.error == "Already translated."

    [result] = files.import_file(translate_xliff(files.export(page, "en", ["fr-ch"], files.XLIFF, options()).content, "[FR2] "),
                                 user=user, overwrite=True, options=options())
    assert result.error == "" and not result.created
    assert texts(page, "fr-ch")[0].title == "[FR2] Swiss chocolate"


def test_source_changed_only_with_the_option(page):
    user = editor()
    xliff = translate_xliff(files.export(page, "en", ["fr-ch"], files.XLIFF, options()).content)
    content = page.get_admin_content("en")
    content.title = "Swiss chocolates"
    content.save()

    [result] = files.import_file(xliff, user=user, options=options())
    assert result.counts["changed"] == 1 and result.counts["ok"] == 2
    assert texts(page, "fr-ch")[0].title == "Swiss chocolates"  # the source's title, as for a new language

    [result] = files.import_file(xliff, user=user, include_changed=True, overwrite=True, options=options())
    assert result.counts["changed"] == 0 and result.counts["ok"] == 3
    assert texts(page, "fr-ch")[0].title == "[FR] Swiss chocolate"


def test_untranslated_invalid_and_missing_are_not_written(page):
    user = editor()
    xliff = files.export(page, "en", ["fr-ch"], files.XLIFF, options()).content
    xliff = translate_xliff(xliff, skip=("page.title",))  # untranslated
    xliff = re.sub(r'(<trans-unit id="page\.menu_title".*?</trans-unit>)', "", xliff, flags=re.S)  # missing
    xliff = re.sub(r"(<target>)(.*?)(</target>)", lambda m: m.group(1) + m.group(2) + '<ph id="99">&lt;br&gt;</ph>' + m.group(3), xliff, flags=re.S)  # invalid

    [result] = files.import_file(xliff, user=user, options=options())

    assert result.counts == {"ok": 0, "changed": 0, "untranslated": 1, "invalid": 1, "missing": 1}
    assert not PageContent.admin_manager.filter(page=page, language="fr-ch").exists()


def test_errors_per_job(page):
    user = editor()
    job = lambda ref, plugin=files.PLUGIN: stfiles.export_xliff([stfiles.FileJob(plugin, ref, "en", "fr-CH", [stfiles.FileSegment("page.title", "Hi")])])  # noqa: E731

    assert files.import_file(job("page:1", "Contao-Supertext-Translation"), user=user)[0].error == "This file belongs to another system (Contao-Supertext-Translation)."
    assert files.import_file(job("node:1:en:fr-ch"), user=user)[0].error == "The page this file was exported from no longer exists."
    assert files.import_file(job("page:999:en:fr-ch"), user=user)[0].error == "The page this file was exported from no longer exists."
    assert files.import_file(job(f"page:{page.pk}:en:nl"), user=user)[0].error == "The site has no language nl."
    reader = User.objects.create_user("reader", "reader@example.com", "pw-123456789", is_staff=True)
    assert files.import_file(job(f"page:{page.pk}:en:fr-ch"), user=reader)[0].error == "You are not allowed to change this page."
    assert not PageContent.admin_manager.filter(page=page, language="fr-ch").exists()


def test_invalid_files_and_size():
    with pytest.raises(files.FileError, match="exported by the Supertext plugin"):
        files.import_file("<html><head><title>x</title></head><body><p>x</p></body></html>", user=None)
    with pytest.raises(files.FileError, match="valid XLIFF or HTML"):
        files.import_file('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>', user=None)
    files.check_size(files.MAX_UPLOAD_BYTES)
    with pytest.raises(files.FileError, match="too large"):
        files.check_size(files.MAX_UPLOAD_BYTES + 1)


def test_dialog_export_and_import(page, client):
    client.force_login(editor())
    response = client.get(reverse("admin:djangocms_supertext_translate", args=[page.pk]) + "?language=en")
    assert b"Export for translation" in response.content and b"Import translation" in response.content

    response = client.post(reverse("admin:djangocms_supertext_export", args=[page.pk]),
                           {"export-source": "en", "export-targets": ["fr-ch"], "export-format": "xliff"})
    assert response.status_code == 200
    assert response["Content-Type"] == "application/x-xliff+xml"
    assert response["Content-Disposition"] == f'attachment; filename="djangocms-page-{page.pk}-fr-CH.xlf"'

    upload = SimpleUploadedFile("fr.xlf", translate_xliff(response.content.decode()).encode(), content_type="application/x-xliff+xml")
    response = client.post(reverse("admin:djangocms_supertext_import", args=[page.pk]), {"import-file": upload})
    assert response.status_code == 200
    assert "Imported: 3" in response.content.decode()
    assert texts(page, "fr-ch")[0].title == "[FR] Swiss chocolate"


def test_dialog_export_html_with_two_languages_is_refused(page, client):
    client.force_login(editor())
    response = client.post(reverse("admin:djangocms_supertext_export", args=[page.pk]),
                           {"export-source": "en", "export-targets": ["fr-ch", "de-ch"], "export-format": "html"})
    assert response.status_code == 200 and response["Content-Type"].startswith("text/html")
    assert b"Choose one language for an HTML file" in response.content


def test_import_needs_the_permission(page, client):
    client.force_login(editor(perm=False))
    upload = SimpleUploadedFile("fr.xlf", b"x")
    assert client.post(reverse("admin:djangocms_supertext_import", args=[page.pk]), {"import-file": upload}).status_code == 403
