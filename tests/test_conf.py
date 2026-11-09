"""Settings and language codes (conf.py): the mapping (LANGUAGES override, else the settings page), else an
exact Supertext code, else the SDK default, else unsupported_language."""

import pytest

from djangocms_supertext import conf
from djangocms_supertext.client import SupertextError


def test_settings(monkeypatch):
    monkeypatch.setenv("SUPERTEXT_API_KEY", "Supertext-Auth-Key env-key")
    monkeypatch.setenv("SUPERTEXT_API_URL", "http://127.0.0.1:8765/v1/")
    options = conf.load({"API_KEY": "settings-key", "LANGUAGES": {"fr": {"code": "fr-CH", "politeness": "less"}}, "PLUGIN_FIELDS": {"HeroPlugin": {"heading": "text"}}})
    assert options.api_key == "env-key" and options.api_key_source == "environment"
    assert options.base_url == "http://127.0.0.1:8765/v1/"
    assert options.target_code("de-ch") == "de-CH"
    assert options.target_code("fr") == "fr-CH" and options.politeness("fr") == "less"
    assert options.plugin_fields["HeroPlugin"] == {"heading": "text"}
    assert options.plugin_fields["TextPlugin"] == {"body": "html"}


def test_exact_supertext_codes_are_used():
    options = conf.load({})
    assert options.target_code("de-ch") == "de-CH"
    assert options.target_code("fr_ch") == "fr-CH"
    assert options.target_code("pt-br") == "pt-BR"
    assert options.target_code("zh-hant") == "zh-Hant"
    assert options.target_code("es") == "es"  # bare: Supertext's code for Spanish
    assert options.target_code("NL") == "nl"


@pytest.mark.parametrize(("code", "expected"), [
    ("de", "de-DE"), ("fr", "fr-FR"), ("en", "en-US"), ("it", "it-IT"), ("pt", "pt-PT"),
    ("es-es", "es"), ("sl-si", "sl"), ("zh-cn", "zh-Hans"), ("zh-tw", "zh-Hant"), ("sr", "sr-Latn"),
])
def test_sdk_defaults(code, expected):
    options = conf.load({}, saved={})
    assert options.target_code(code) == expected


@pytest.mark.parametrize("code", ["en-ie", "de-li", "gsw", "sr-rs", "xx"])
def test_no_guessing(code):
    options = conf.load({}, saved={})
    with pytest.raises(SupertextError) as info:
        options.target_code(code)
    assert info.value.code == "unsupported_language"
    assert info.value.params == {"language": code}
    assert "has no Supertext language yet" in str(info.value)
    assert options.target_code_or_none(code) is None


def test_mapping_wins():
    options = conf.load({"LANGUAGES": {"de": {"code": "de-CH"}, "zh-cn": {"code": "zh-Hans"}, "en": {"code": " en-GB "}}})
    assert options.target_code("de") == "de-CH"
    assert options.target_code("zh_CN") == "zh-Hans"  # keys compare like codes
    assert options.target_code("en") == "en-GB"
    assert options.mapping() == {"de": "de-CH", "zh-cn": "zh-Hans", "en": "en-GB"}


def test_settings_page_mapping_and_override():
    saved = {"de": {"code": "de-CH", "politeness": "more"}, "fr": {"code": "fr-CH", "politeness": "default"}, "ch": {"code": "gsw-u-sd-chzh"}}
    options = conf.load({"LANGUAGES": {"fr": {"code": "fr-FR", "politeness": "less"}}}, saved=saved)
    assert options.target_code("de") == "de-CH" and options.politeness("de") == "more"  # the settings page
    assert options.target_code("fr") == "fr-FR" and options.politeness("fr") == "less"  # LANGUAGES wins
    assert options.override_code("fr") == "fr-FR" and options.saved_code("fr") == "fr-CH"
    assert options.source_code("ch") == "gsw" and options.target_code("ch") == "gsw-u-sd-chzh"
    assert options.target_code("it") == "it-IT"  # not chosen: the SDK default


def test_source_codes():
    options = conf.load({"LANGUAGES": {"de": {"code": "de-CH"}, "ch": {"code": "gsw-u-sd-chzh"}}})
    assert options.target_code("de") == "de-CH"  # one mapping for both directions
    assert options.source_code("en") == "en"
    assert options.source_code("en-gb") == "en"
    assert options.source_code("de") == "de"  # from its mapping de-CH
    assert options.source_code("ch") == "gsw"
    with pytest.raises(SupertextError) as info:
        options.source_code("xx")
    assert info.value.code == "unsupported_language" and info.value.params == {"language": "xx"}


def test_english_source_with_en_us_mapping():
    options = conf.load({"LANGUAGES": {"en": {"code": "en-US"}}})
    assert options.target_code("en") == "en-US"
    assert options.source_code("en") == "en"


def test_version_reports_setting(monkeypatch):
    assert conf.load({}).reports_enabled is True  # default on
    assert conf.load({"VERSION_REPORTS": False}).reports_enabled is False
    monkeypatch.setenv("SUPERTEXT_VERSION_REPORTS", "0")
    options = conf.load({"VERSION_REPORTS": True})
    assert options.reports_enabled is False and options.reports_from_environment
    monkeypatch.setenv("SUPERTEXT_VERSION_REPORTS", "1")
    assert conf.load({"VERSION_REPORTS": False}).reports_enabled is True
    assert conf.load({"SITE_URL": "https://www.example.ch/"}).site_url == "https://www.example.ch"


def test_review_url_defaults_to_supertexts_review_service(monkeypatch):
    options = conf.load({})
    assert options.review_url == conf.REVIEW_URL == "https://localizationreview-production.up.railway.app/v1/"
    assert options.review_enabled and options.client().review_url == conf.REVIEW_URL
    assert conf.load({"REVIEW_URL": ""}).review_enabled is False
    assert conf.load({"REVIEW_URL": None}).review_url == ""
    assert conf.load({"REVIEW_URL": "https://api.supertext.com/v1/"}).review_enabled is False  # the API itself: no second client
    monkeypatch.setenv("SUPERTEXT_REVIEW_URL", "http://127.0.0.1:3000/v1/")
    assert conf.load({"REVIEW_URL": ""}).review_url == "http://127.0.0.1:3000/v1/"


def test_review_per_language_off_by_default_and_override_wins():
    options = conf.load({"LANGUAGES": {"fr-ch": {"review": False}, "it-ch": {"review": True}}}, saved={"de-ch": {"code": "", "review": True}, "fr-ch": {"review": True}})
    assert options.review("de-ch") is True and options.review("DE_CH") is True
    assert options.review("fr-ch") is False  # LANGUAGES wins over the settings page
    assert options.review("it-ch") is True
    assert options.review("en") is False
