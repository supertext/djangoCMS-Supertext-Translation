"""
Translates a django CMS page from one language into others.

The page's texts in the source language (title, page title, menu title, meta description,
and the configured fields of its plugins, e.g. a Text plugin's body) go to Supertext as one
HTML document per target language, one ``data-st-id`` element per value. The target
language's content is then created (or, with ``overwrite``, replaced): the page fields are
set, the source's plugins are copied into the target's placeholders and their texts replaced
with the translation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from django.db import transaction
from django.utils.translation import gettext as _

from . import conf
from .client import Segment, SupertextClient, SupertextError

logger = logging.getLogger(__name__)

#: PageContent fields that are translated (all plain text).
PAGE_FIELDS = ("title", "page_title", "menu_title", "meta_description")
#: PageContent settings copied from the source when a language is created.
COPIED_PAGE_SETTINGS = ("template", "in_navigation", "soft_root", "limit_visibility_in_menu", "xframe_options")


@dataclass
class Result:
    language: str
    status: str  # translated | skipped | error
    message: str = ""
    created: bool = False
    code: str = ""  # the SDK's error code for errors (e.g. authentication_failure, unsupported_language)
    http_status: int | None = None


@dataclass
class _Unit:
    """One value to translate: a page field (plugin is None) or a plugin field (plugin index)."""

    field: str
    kind: str  # text | html
    value: str
    plugin: int | None = None
    plugin_pk: int | None = None

    @property
    def key(self) -> str:
        """Stable key for translation files: ``page.title``, ``plugin.12.body`` (the source plugin's pk)."""
        return f"page.{self.field}" if self.plugin is None else f"plugin.{self.plugin_pk}.{self.field}"


@dataclass
class _Source:
    content: object
    plugins_by_slot: dict[str, list] = field(default_factory=dict)
    units: list[_Unit] = field(default_factory=list)


def page_content(page, language):
    """The latest content of ``page`` in ``language`` (drafts included), or None."""
    from cms.models import PageContent

    return PageContent.admin_manager.filter(page=page, language=language).latest_content().first()


def page_site_id(page) -> int:
    """django CMS 5 has Page.site_id; 4.x keeps the site on the tree node."""
    site_id = getattr(page, "site_id", None)
    return site_id if site_id is not None else page.node.site_id


def site_languages(page) -> list[dict]:
    from cms.utils.i18n import get_language_list, get_language_object

    site_id = page_site_id(page)
    out = []
    for code in get_language_list(site_id):
        language = get_language_object(code, site_id)
        out.append({"code": code, "name": str(language.get("name", code))})
    return out


def describe(page) -> list[dict]:
    """Languages of the page's site: whether the page exists in it and its last Supertext translation."""
    from .models import Translation

    last = {}
    for item in Translation.objects.filter(page=page, status=Translation.STATUS_TRANSLATED).order_by("created"):
        last[item.target_language] = item.created
    return [
        {**language, "exists": page_content(page, language["code"]) is not None, "last_translation": last.get(language["code"])}
        for language in site_languages(page)
    ]


def localized(error: SupertextError) -> str:
    """The error's message in the current admin language (the API's own detail stays as sent)."""
    template = getattr(error, "template", None)
    if not template:
        return str(error)
    params = getattr(error, "params", None) or {}
    text = _(template) % params if params else _(template)
    if getattr(error, "detail", ""):
        text += f" ({error.detail})"
    return text


def translate_page(page, source_language: str, targets: list[str], overwrite: bool = False, user=None,
                   options: conf.Options | None = None, client: SupertextClient | None = None) -> list[Result]:
    from .models import Translation

    options = options or conf.load()
    source = _collect(page, source_language, options)
    if source is None:
        raise SupertextError(_("The page has no %(language)s version to translate from.") % {"language": source_language})
    if not options.api_key and client is None:
        raise SupertextError(_("No Supertext API key is configured. Set SUPERTEXT_API_KEY."))
    client = client or options.client()

    results: list[Result] = []
    for target in dict.fromkeys(targets):
        if target == source_language:
            continue
        existing = page_content(page, target)
        if existing is not None and not overwrite:
            results.append(Result(target, Translation.STATUS_SKIPPED, _("Already translated.")))
            continue
        try:
            if existing is not None:
                _check_editable(existing)
            # Translation review: languages with it on go through the review service (same protocol).
            translated = _translate(client.for_review(options.review(target)), source.units, source_language, target, options)
            with transaction.atomic():
                created = _apply(page, source, translated, target, existing, user)
            results.append(Result(target, Translation.STATUS_TRANSLATED, created=created))
        except SupertextError as error:
            results.append(Result(target, Translation.STATUS_ERROR, localized(error), code=error.code, http_status=error.status))
        except Exception as error:  # noqa: BLE001 - shown per language, logged with traceback
            logger.exception("Supertext translation of page %s into %s failed", page.pk, target)
            results.append(Result(target, Translation.STATUS_ERROR, str(error) or error.__class__.__name__))

    Translation.objects.bulk_create([
        Translation(page=page, source_language=source_language, target_language=r.language, status=r.status,
                    message=r.message, user=user if getattr(user, "pk", None) else None)
        for r in results
    ])
    return results


def collect(page, language: str, options: conf.Options) -> _Source | None:
    """The page's texts in ``language`` (page fields and plugin fields), or None when the page has
    no content in it. The API translation and the translation files use the same units."""
    return _collect(page, language, options)


def apply(page, source: _Source, translated: dict[int, str], language: str, user=None, overwrite: bool = False) -> bool:
    """Writes translations (unit index → text) into ``language`` exactly as an API translation does:
    creates the language, or with ``overwrite`` replaces it (only drafts with djangocms-versioning).
    Raises :class:`SupertextError` for a language that exists without ``overwrite``. Returns whether
    the language was created."""
    existing = page_content(page, language)
    if existing is not None and not overwrite:
        raise SupertextError(_("Already translated."))
    if existing is not None:
        _check_editable(existing)
    with transaction.atomic():
        return _apply(page, source, translated, language, existing, user)


def _collect(page, language: str, options: conf.Options) -> _Source | None:
    from cms.utils.plugins import downcast_plugins

    content = page_content(page, language)
    if content is None:
        return None
    source = _Source(content=content)
    for name in PAGE_FIELDS:
        value = (getattr(content, name, None) or "").strip()
        if value:
            source.units.append(_Unit(name, "text", value))

    index = 0
    for placeholder in content.get_placeholders():
        plugins = list(downcast_plugins(placeholder.get_plugins(language).order_by("position")))
        source.plugins_by_slot[placeholder.slot] = plugins
        for plugin in plugins:
            for name, kind in options.plugin_fields.get(plugin.plugin_type, {}).items():
                value = getattr(plugin, name, None)
                if isinstance(value, str) and value.strip():
                    source.units.append(_Unit(name, "html" if kind == "html" else "text", value.strip(), plugin=index, plugin_pk=plugin.pk))
            plugin._supertext_index = index
            index += 1
    return source


def _translate(client: SupertextClient, units: list[_Unit], source: str, target: str, options: conf.Options) -> dict[int, str]:
    segments = [Segment(unit.value, html=unit.kind == "html") for unit in units]
    return client.translate_segments(
        segments,
        target_language=options.target_code(target),
        source_language=options.source_code(source),
        politeness=options.politeness(target),
    )


def _check_editable(content) -> None:
    """With djangocms-versioning, only drafts may be changed."""
    from django.apps import apps

    if not apps.is_installed("djangocms_versioning"):
        return
    try:
        from djangocms_versioning.constants import DRAFT
        from djangocms_versioning.models import Version
    except ImportError:
        return
    version = Version.objects.get_for_content(content)
    if version is not None and version.state != DRAFT:
        raise SupertextError(_("This language is published. Create a draft of it, then translate again."))


_INLINE_PLUGIN = re.compile(r'(<cms-plugin\b[^>]*?\bid=")(\d+)(")')


def _remap_inline_plugins(html: str, new_ids: dict[str, str]) -> str:
    return _INLINE_PLUGIN.sub(lambda m: m.group(1) + new_ids.get(m.group(2), m.group(2)) + m.group(3), html)


def _apply(page, source: _Source, translated: dict[int, str], language: str, existing, user) -> bool:
    from cms.api import create_page_content

    values = {unit.field: translated.get(i, "").strip() for i, unit in enumerate(source.units) if unit.plugin is None}
    values = {name: value for name, value in values.items() if value}
    created = existing is None

    if created:
        title = values.get("title") or source.content.title
        content = create_page_content(
            language, title, page,
            menu_title=values.get("menu_title") or None,
            page_title=values.get("page_title") or None,
            meta_description=values.get("meta_description") or None,
            created_by=user if getattr(user, "pk", None) else "Supertext",
            **{name: getattr(source.content, name) for name in COPIED_PAGE_SETTINGS},
        )
    else:
        content = existing
        for name, value in values.items():
            setattr(content, name, value)
        if user is not None and getattr(user, "pk", None):
            content.changed_by = str(user)
        content.save()

    # Plugins: replace the target's plugins with copies of the source's, then put in the translations.
    targets = {slot: placeholder for slot, placeholder in content.rescan_placeholders().items() if placeholder is not None}

    by_plugin: dict[int, dict[str, str]] = {}
    for i, unit in enumerate(source.units):
        if unit.plugin is not None and translated.get(i, "").strip():
            by_plugin.setdefault(unit.plugin, {})[unit.field] = translated[i].strip()

    for slot, plugins in source.plugins_by_slot.items():
        placeholder = targets.get(slot)
        if placeholder is None:
            continue
        old = list(placeholder.get_plugins(language).filter(parent__isnull=True))
        if old:
            if hasattr(placeholder, "delete_plugins"):  # django CMS 5.1+
                placeholder.delete_plugins(old)
            else:
                for plugin in old:
                    placeholder.delete_plugin(placeholder.get_plugins(language).get(pk=plugin.pk))
        if not plugins:
            continue
        copies = _copy_plugins(plugins, placeholder, language)
        # Text bodies reference their inline plugins (<cms-plugin id="…">): point them at the copies.
        new_ids = {str(original.pk): str(copy.pk) for original, copy in zip(plugins, copies)}
        for original, copy in zip(plugins, copies):
            fields = by_plugin.get(original._supertext_index)
            if not fields:
                continue
            copy = copy.get_bound_plugin() if hasattr(copy, "get_bound_plugin") else copy
            for name, value in fields.items():
                setattr(copy, name, _remap_inline_plugins(value, new_ids))
            copy.save()

    if hasattr(page, "_clear_internal_cache"):  # django CMS 5
        page._clear_internal_cache()
    return created


def _copy_plugins(plugins, placeholder, language):
    import inspect

    from cms.utils.plugins import copy_plugins_to_placeholder

    if "plugins_are_downcast" in inspect.signature(copy_plugins_to_placeholder).parameters:  # django CMS 5
        return copy_plugins_to_placeholder(plugins, placeholder, language=language, plugins_are_downcast=True)
    return copy_plugins_to_placeholder(plugins, placeholder, language=language)
