"""
Settings: the ``SUPERTEXT`` dict in Django settings, plus environment variables.

    SUPERTEXT = {
        "API_KEY": "...",                 # or the SUPERTEXT_API_KEY environment variable (wins)
        "ENVIRONMENT": "live",            # live | staging | testing
        "API_URL": "",                    # custom base URL; or SUPERTEXT_API_URL (wins)
        "REVIEW_URL": REVIEW_URL,         # review service for languages with Translation review; "" = off; or SUPERTEXT_REVIEW_URL (wins)
        "LANGUAGES": {"de": {"code": "de-CH", "politeness": "more", "review": True}},  # optional override of the settings page
        "TIMEOUT": 180,                   # seconds per language
        "PLUGIN_FIELDS": {"MyPlugin": {"heading": "text", "content": "html"}},
        "VERSION_REPORTS": True,          # "Send version information to Supertext"; SUPERTEXT_VERSION_REPORTS (wins)
        "SITE_URL": "",                   # the site's base URL for version reports (default: the request's)
    }

Language codes follow the Supertext SDK (``Languages.target``/``source``): the mapping wins (the
``code`` under ``LANGUAGES``, else the Supertext language chosen on the settings page, stored in
:class:`~djangocms_supertext.models.LanguageSetting`); otherwise a django CMS code that is a Supertext
code apart from case and ``_``/``-`` (``de-ch`` → ``de-CH``, ``es``); otherwise the SDK's default
(``de`` → ``de-DE``, ``en`` → ``en-US``, ``es-es`` → ``es``, ``zh-tw`` → ``zh-Hant``); anything else
(``en-ie``, ``gsw``) is ``unsupported_language``. The form of address works the same way:
``politeness`` under ``LANGUAGES`` wins over the settings page, and so does ``review`` (*Translation
review*: translations into that language go through the review service at ``REVIEW_URL``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from ._vendor import plugin_health
from ._vendor.supertext import v1 as sdk
from .client import API_KEY_URL, REVIEW_URL, SIGNUP_URL, Languages, SupertextClient, SupertextError, base_url_for, normalize_key  # noqa: F401 (URLs re-exported)


#: Plugin fields translated out of the box: plugin type -> {model field: "text" | "html"}.
DEFAULT_PLUGIN_FIELDS: dict[str, dict[str, str]] = {
    "TextPlugin": {"body": "html"},  # djangocms-text (and djangocms-text-ckeditor)
    "LinkPlugin": {"name": "text"},  # djangocms-link
    "PicturePlugin": {"caption_text": "text"},  # djangocms-picture
    "FilePlugin": {"file_name": "text"},  # djangocms-file
    "VideoPlayerPlugin": {"label": "text"},  # djangocms-video
}


def _key(language_code: str) -> str:
    """Language codes compare like the SDK's: case, ``_``/``-`` and spaces don't matter."""
    return language_code.strip().replace("_", "-").lower()


@dataclass
class Options:
    api_key: str = ""
    api_key_source: str = ""  # "environment", "settings" or ""
    environment: str = "live"
    api_url: str = ""
    review_url: str = REVIEW_URL  # "" = Translation review off for every language
    languages: dict[str, dict[str, str]] = field(default_factory=dict)  # LANGUAGES in the SUPERTEXT setting (override)
    saved: dict[str, dict[str, str]] = field(default_factory=dict)  # the settings page (LanguageSetting rows)
    timeout: float = 180
    poll_interval: float = 2
    plugin_fields: dict[str, dict[str, str]] = field(default_factory=dict)
    version_reports: bool | None = None  # the VERSION_REPORTS setting (None: not set, default on)
    site_url: str = ""

    @property
    def base_url(self) -> str:
        return base_url_for(self.environment, self.api_url)

    @property
    def reports_enabled(self) -> bool:
        """*Send version information to Supertext*: SUPERTEXT_VERSION_REPORTS wins over VERSION_REPORTS (default on)."""
        return plugin_health.reports_enabled(self.version_reports)

    @property
    def reports_from_environment(self) -> bool:
        return (os.environ.get("SUPERTEXT_VERSION_REPORTS") or "").strip().lower() in ("0", "false", "off", "no", "1", "true", "on", "yes")

    def mapping(self) -> dict[str, str]:
        """django CMS language → Supertext code: the settings page, overridden by ``LANGUAGES`` → ``code``."""
        result = {_key(cms_code): code for cms_code, entry in self.saved.items() if (code := str((entry or {}).get("code") or "").strip())}
        for cms_code, entry in self.languages.items():
            if code := str((entry or {}).get("code") or "").strip():
                result[_key(cms_code)] = code
        return result

    def target_code(self, language_code: str) -> str:
        """Supertext target for a django CMS language: the mapping, else an exact Supertext code
        (``de-ch`` → ``de-CH``), else the SDK default (``de`` → ``de-DE``), else :class:`SupertextError`
        ``unsupported_language`` (nothing is sent)."""
        try:
            return Languages.target(language_code, self.mapping())
        except sdk.SupertextError as error:
            raise SupertextError.from_sdk(error) from error

    def target_code_or_none(self, language_code: str) -> str | None:
        """The target code, or None when the language has no Supertext language yet (settings page)."""
        try:
            return self.target_code(language_code)
        except SupertextError:
            return None

    def source_code(self, language_code: str) -> str:
        """Supertext source for a django CMS language: the mapping in its source form (one mapping
        for both directions: ``de-CH`` → ``de``), else the code's language (``en-us`` → ``en``), else
        ``unsupported_language``."""
        try:
            return Languages.source(language_code, self.mapping())
        except sdk.SupertextError as error:
            raise SupertextError.from_sdk(error) from error

    def mapping_for(self, language_code: str) -> str:
        """The mapped Supertext code (override or settings page), or ``""``."""
        return self.mapping().get(_key(language_code), "")

    def override_code(self, language_code: str) -> str:
        """The code under ``LANGUAGES`` in the SUPERTEXT setting (wins over the settings page), or ``""``."""
        return str(_lookup(self.languages, language_code).get("code") or "").strip()

    def override_politeness(self, language_code: str) -> str:
        value = _lookup(self.languages, language_code).get("politeness") or ""
        return value if value in ("default", "more", "less") else ""

    def saved_code(self, language_code: str) -> str:
        return str(_lookup(self.saved, language_code).get("code") or "").strip()

    def politeness(self, language_code: str) -> str:
        value = self.override_politeness(language_code) or _lookup(self.saved, language_code).get("politeness") or "default"
        return value if value in ("more", "less") else "default"

    def override_review(self, language_code: str) -> bool | None:
        """``review`` under ``LANGUAGES`` in the SUPERTEXT setting (wins over the settings page), or None."""
        return _bool_or_none(_lookup(self.languages, language_code).get("review"))

    def saved_review(self, language_code: str) -> bool:
        return bool(_lookup(self.saved, language_code).get("review"))

    def review(self, language_code: str) -> bool:
        """*Translation review* for translations into this language (override, else the settings page; off by default)."""
        override = self.override_review(language_code)
        return self.saved_review(language_code) if override is None else override

    @property
    def review_enabled(self) -> bool:
        """Whether a review service is set (``REVIEW_URL`` not empty and not the API itself)."""
        url = self.review_url.strip().rstrip("/")
        return bool(url) and url != self.base_url.rstrip("/")

    def language(self, language_code: str) -> dict[str, str]:
        return _lookup(self.languages, language_code)

    def client(self, **kwargs) -> SupertextClient:
        """The Supertext client; ``client.for_review(options.review(language))`` gives the review service's."""
        return SupertextClient(self.api_key, self.base_url, poll_timeout=self.timeout, poll_interval=self.poll_interval, review_url=self.review_url, **kwargs)


def _lookup(entries: dict[str, dict[str, str]], language_code: str) -> dict[str, str]:
    wanted = _key(language_code)
    for key, entry in entries.items():
        if _key(key) == wanted:
            return entry or {}
    return {}


def saved_languages() -> dict[str, dict[str, str]]:
    """The languages chosen on the settings page (``{}`` while the database isn't ready)."""
    try:
        from .models import LanguageSetting

        return {
            row.language: {"code": row.supertext_code, "politeness": row.politeness, "review": row.review}
            for row in LanguageSetting.objects.all()
        }
    except Exception:  # noqa: BLE001 - no table yet (before migrate), no database access (checks, tests)
        return {}


def _bool_or_none(value) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "off", "no")
    return bool(value)


def _review_url(options: dict) -> str:
    """SUPERTEXT_REVIEW_URL (when set), else ``REVIEW_URL`` (``""`` turns review off), else Supertext's review service."""
    env = os.environ.get("SUPERTEXT_REVIEW_URL", "").strip()
    if env:
        return env
    value = options.get("REVIEW_URL", REVIEW_URL)
    return "" if value is None else str(value).strip()


def load(options: dict | None = None, *, saved: dict[str, dict[str, str]] | None = None) -> Options:
    """The settings: ``options`` (default: the ``SUPERTEXT`` setting) and ``saved`` (default: the
    languages chosen on the settings page)."""
    if options is None:
        from django.conf import settings

        options = getattr(settings, "SUPERTEXT", None) or {}

    env_key = os.environ.get("SUPERTEXT_API_KEY", "")
    key = env_key or str(options.get("API_KEY") or "")
    plugin_fields = {k: dict(v) for k, v in DEFAULT_PLUGIN_FIELDS.items()}
    for plugin_type, fields in (options.get("PLUGIN_FIELDS") or {}).items():
        plugin_fields[str(plugin_type)] = {str(name): str(kind) for name, kind in (fields or {}).items()}
    return Options(
        api_key=normalize_key(key),
        api_key_source="environment" if env_key else ("settings" if key else ""),
        environment=str(options.get("ENVIRONMENT") or "live"),
        api_url=os.environ.get("SUPERTEXT_API_URL", "") or str(options.get("API_URL") or ""),
        review_url=_review_url(options),
        languages={str(k): dict(v or {}) for k, v in (options.get("LANGUAGES") or {}).items()},
        saved=saved_languages() if saved is None else saved,
        timeout=float(options.get("TIMEOUT") or 180),
        poll_interval=float(options.get("POLL_INTERVAL") or 2),
        plugin_fields=plugin_fields,
        version_reports=_bool_or_none(options.get("VERSION_REPORTS")),
        site_url=str(options.get("SITE_URL") or "").strip().rstrip("/"),
    )
