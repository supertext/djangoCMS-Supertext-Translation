"""
"Export for translation" and "Import translation": a page as an XLIFF 1.2 or HTML file (the
Supertext SDK's ``files``), translated outside the API, and the translated file back into the
page's language.

The segments are the units an API translation sends (``translator.collect``: page fields and
plugin fields), keyed ``page.<field>`` and ``plugin.<source plugin pk>.<field>``. The import
collects them again and writes through ``translator.apply``, the API translation's write-back
(new languages created, existing ones only with "Overwrite existing translations", drafts only
with djangocms-versioning, the source's plugins copied).

Reference (stored in the file): ``page:<page id>:<source language>:<target language>`` with
django CMS language codes, e.g. ``page:12:en:fr-ch``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from django.utils.translation import gettext as _

from . import conf, translator
from ._vendor.supertext import files as stfiles
from .client import SupertextError
from .translator import localized

logger = logging.getLogger(__name__)

#: The repository name, written into every file as the job's plugin.
PLUGIN = "djangoCMS-Supertext-Translation"
#: Uploads larger than this are refused before they are read.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

XLIFF = "xliff"
HTML = "html"

_REFERENCE = re.compile(r"page:([1-9][0-9]*):([A-Za-z0-9_-]{1,15}):([A-Za-z0-9_-]{1,15})")


class FileError(Exception):
    """An export or import that can't go ahead; ``str(error)`` is the message in the admin language."""


@dataclass
class ExportedFile:
    name: str
    content_type: str
    content: str


@dataclass
class JobResult:
    """One job (page × language) of an imported file."""

    reference: str
    title: str = ""
    language: str = ""
    error: str = ""
    counts: dict[str, int] = field(default_factory=lambda: {"ok": 0, "changed": 0, "untranslated": 0, "invalid": 0, "missing": 0})
    created: bool = False


def reference(page_id: int, source: str, target: str) -> str:
    return f"page:{page_id}:{source}:{target}"


def parse_reference(value: str) -> tuple[int, str, str] | None:
    match = _REFERENCE.fullmatch(value or "")
    return (int(match.group(1)), match.group(2), match.group(3)) if match else None


def language_code(options: conf.Options, code: str, target: bool) -> str:
    """The Supertext code for a django CMS language (the mapping, the exact match, the SDK default);
    a language Supertext doesn't know keeps its own code with ``-`` (``en_IE`` → ``en-IE``), so a
    file can still go to any translator."""
    try:
        return options.target_code(code) if target else options.source_code(code)
    except SupertextError:
        return code.replace("_", "-")


def check_size(size: int) -> None:
    if size > MAX_UPLOAD_BYTES:
        raise FileError(_("The file is too large (at most 10 MB)."))


def segments(source) -> list[stfiles.FileSegment]:
    return [stfiles.FileSegment(unit.key, unit.value, html=unit.kind == "html") for unit in source.units]


def export(page, source_language: str, targets: list[str], fmt: str, options: conf.Options | None = None) -> ExportedFile:
    """The page in ``source_language`` as one XLIFF file (one job per target language) or one HTML
    file (exactly one target language)."""
    options = options or conf.load()
    targets = [t for t in dict.fromkeys(targets) if t != source_language]
    if not targets or (fmt == HTML and len(targets) != 1):
        raise FileError(_("Choose one language for an HTML file, or one or more for XLIFF."))
    source = translator.collect(page, source_language, options)
    if source is None:
        raise FileError(_("The page has no %(language)s version to translate from.") % {"language": source_language})
    items = segments(source)
    if not items:
        raise FileError(_("Nothing to translate."))
    jobs = [
        stfiles.FileJob(PLUGIN, reference(page.pk, source_language, target), language_code(options, source_language, False),
                        language_code(options, target, True), items)
        for target in targets
    ]
    base = f"djangocms-page-{page.pk}"
    if len(jobs) == 1:
        base += "-" + re.sub(r"[^A-Za-z0-9-]+", "-", jobs[0].target_language)
    if fmt == HTML:
        return ExportedFile(base + ".html", "text/html; charset=utf-8", stfiles.export_html(jobs[0]))
    return ExportedFile(base + ".xlf", "application/x-xliff+xml", stfiles.export_xliff(jobs))


def import_file(content: bytes | str, *, user, include_changed: bool = False, overwrite: bool = False,
                options: conf.Options | None = None) -> list[JobResult]:
    """Imports a translated file: one result per job. Raises :class:`FileError` for a file that
    can't be read (too large, not XLIFF or HTML, no metadata)."""
    options = options or conf.load()
    check_size(len(content))
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise FileError(_("This file isn't a valid XLIFF or HTML translation file.")) from None
    try:
        files = stfiles.read(content)
    except stfiles.TranslationFileError as error:
        if error.code == "missing_metadata":
            raise FileError(_("This file wasn't exported by the Supertext plugin, or its header was removed.")) from None
        if error.code == "too_large":
            raise FileError(_("The file is too large (at most 10 MB).")) from None
        raise FileError(_("This file isn't a valid XLIFF or HTML translation file.")) from None
    return [_import_job(file, user, include_changed, overwrite, options) for file in files]


def _import_job(file, user, include_changed: bool, overwrite: bool, options: conf.Options) -> JobResult:
    from cms.models import Page

    from .models import Translation

    result = JobResult(file.reference, title=file.reference, language=file.target_language)
    if file.plugin != PLUGIN:
        result.error = _("This file belongs to another system (%(plugin)s).") % {"plugin": file.plugin}
        return result
    parsed = parse_reference(file.reference)
    page = Page.objects.filter(pk=parsed[0]).first() if parsed else None
    if page is None:
        result.error = _("The page this file was exported from no longer exists.")
        return result
    _page_id, source_language, target = parsed
    result.title = str(page)
    languages = {lang["code"]: lang["name"] for lang in translator.site_languages(page)}
    for code in (target, source_language):
        if code not in languages:
            result.error = _("The site has no language %(language)s.") % {"language": code}
            return result
    result.language = languages[target]
    if not page.has_change_permission(user):
        result.error = _("You are not allowed to change this page.")
        return result
    source = translator.collect(page, source_language, options)
    if source is None:
        result.error = _("The page has no %(language)s version to translate from.") % {"language": source_language}
        return result

    index = {unit.key: i for i, unit in enumerate(source.units)}
    translated: dict[int, str] = {}
    for segment in stfiles.import_translations(file, segments(source)):
        if segment.status == "ok" or (segment.status == "source_changed" and include_changed):
            translated[index[segment.key]] = segment.text or ""
        elif segment.status == "source_changed":
            result.counts["changed"] += 1
        elif segment.status == "untranslated":
            result.counts["untranslated"] += 1
        elif segment.status == "invalid_markup":
            result.counts["invalid"] += 1
        else:
            result.counts["missing"] += 1

    if not translated:
        return result
    try:
        result.created = translator.apply(page, source, translated, target, user=user, overwrite=overwrite)
    except SupertextError as error:
        result.error = localized(error)
        return result
    except Exception as error:  # noqa: BLE001 - shown per job, logged with traceback
        logger.exception("Supertext file import into page %s (%s) failed", page.pk, target)
        result.error = str(error) or error.__class__.__name__
        return result
    result.counts["ok"] = len(translated)
    Translation.objects.create(page=page, source_language=source_language, target_language=target,
                               status=Translation.STATUS_TRANSLATED, message=file.format.upper(),
                               user=user if getattr(user, "pk", None) else None)
    return result
