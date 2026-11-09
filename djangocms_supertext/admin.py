"""
Admin: the list of Supertext translations, the translate dialog (opened from the django CMS
toolbar) and the Supertext settings page with "Test connection".

    /admin/djangocms_supertext/translation/                    list (view permission)
    /admin/djangocms_supertext/translation/page/<page_id>/     translate dialog
    /admin/djangocms_supertext/translation/page/<page_id>/export/   Export for translation (file download)
    /admin/djangocms_supertext/translation/page/<page_id>/import/   Import translation (file upload)
    /admin/djangocms_supertext/translation/settings/           settings, languages and Test connection (superusers)
    /admin/djangocms_supertext/languagesetting/                the saved languages in the plain Django admin (superusers)
    /admin/djangocms_supertext/translation/ping/               public: the Commando Center's ping (views.ping)
"""

from __future__ import annotations

import re

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.dateparse import parse_datetime
from django.utils.translation import get_language, get_language_info
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from . import __version__, conf, files, reporting, translator, views
from .client import SupertextError
from .translator import localized
from .models import LanguageSetting, Translation

PERMISSION = "djangocms_supertext.translate"
RELEASES_URL = "https://github.com/Supertext/djangoCMS-Supertext-Translation/releases/tag/v{version}"


def plugin_version() -> dict:
    """The installed package version (``djangocms_supertext.__version__``) and, for a release
    (X.Y.Z), the link to its GitHub release."""
    version = __version__
    url = RELEASES_URL.format(version=version) if re.fullmatch(r"\d+\.\d+\.\d+", version) else ""
    return {"number": version, "url": url}


# -- Supertext languages (the combo boxes) -------------------------------------------------------


def target_label(target) -> str:
    """``Name (code)`` for a Supertext target, the name in the admin's language where Django knows it."""
    name = target.name
    if (get_language() or "en").split("-")[0] != "en":
        code = target.code.lower()
        for candidate in (code, code.split("-")[0]):
            try:
                name = get_language_info(candidate)["name_translated"]
                break
            except KeyError:
                continue
    return f"{name} ({target.code})"


def target_choices(blank: bool = True) -> list[tuple[str, str]]:
    """The select's options: "— choose —" and Supertext's targets (the SDK's ``target_options()``)."""
    choices = [(target.code, target_label(target)) for target in conf.Languages.target_options()]
    return ([("", _("— choose —"))] if blank else []) + choices


def _politeness_targets() -> list[str]:
    return [target.code for target in conf.Languages.TARGETS if target.politeness]


def clean_target(value: str) -> str:
    value = (value or "").strip()
    if value and not conf.Languages.is_supported_target(value):
        raise forms.ValidationError(_("%(code)s is not a Supertext language.") % {"code": value})
    return conf.Languages.match_target(value) or ""


def clean_politeness(target: str, politeness: str) -> str:
    """Formal/informal only where Supertext offers it for the chosen target."""
    if politeness not in ("more", "less") or not target or not conf.Languages.supports_politeness(target):
        return "default"
    return politeness


class LanguageSettingForm(forms.ModelForm):
    """The plain Django admin form: the Supertext language as a select, validated against the SDK's list."""

    supertext_code = forms.ChoiceField(label=gettext_lazy("Supertext language"), required=False)

    class Meta:
        model = LanguageSetting
        fields = ["language", "supertext_code", "politeness", "review"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supertext_code"].choices = target_choices()

    def clean_supertext_code(self):
        return clean_target(self.cleaned_data.get("supertext_code"))

    def clean(self):
        data = super().clean()
        data["politeness"] = clean_politeness(data.get("supertext_code") or "", data.get("politeness") or "default")
        return data


@admin.register(LanguageSetting)
class LanguageSettingAdmin(admin.ModelAdmin):
    form = LanguageSettingForm
    list_display = ("language", "supertext_code", "politeness", "review")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    has_add_permission = has_change_permission = has_delete_permission = has_view_permission


def cms_languages() -> list[dict]:
    """Every django CMS language of every site, once (the mapping is per language, not per site)."""
    from cms.utils.i18n import get_languages
    from django.contrib.sites.models import Site

    seen: dict[str, dict] = {}
    for site in Site.objects.order_by("pk"):
        for lang in get_languages(site.pk):
            entry = seen.setdefault(lang["code"], {"code": lang["code"], "name": lang.get("name", lang["code"]), "sites": []})
            entry["sites"].append(site)
    return list(seen.values())


def save_languages(request, languages: list[dict], options: conf.Options) -> list[str]:
    """Saves the posted combo boxes (``target-<code>``, ``politeness-<code>``) and checkboxes
    (``review-<code>``, *Translation review*); returns the errors.
    Languages set under LANGUAGES in the SUPERTEXT setting are left alone (that setting wins)."""
    errors = []
    for lang in languages:
        code = lang["code"]
        if options.override_code(code):
            target = options.saved_code(code)  # the select is disabled: keep what was saved
        else:
            try:
                target = clean_target(request.POST.get(f"target-{code}", ""))
            except forms.ValidationError as error:
                errors.extend(f"{lang['name']}: {message}" for message in error.messages)
                continue
        if options.override_politeness(code):
            politeness = _saved_politeness(options, code)
        else:
            politeness = clean_politeness(options.override_code(code) or target, request.POST.get(f"politeness-{code}", "default"))
        if options.override_review(code) is not None or not options.review_enabled:
            review = options.saved_review(code)  # the checkbox is disabled: keep what was saved
        else:
            review = bool(request.POST.get(f"review-{code}"))
        LanguageSetting.objects.update_or_create(language=code, defaults={"supertext_code": target, "politeness": politeness, "review": review})
    return errors


def _saved_politeness(options: conf.Options, code: str) -> str:
    value = conf._lookup(options.saved, code).get("politeness") or "default"
    return value if value in ("more", "less") else "default"


class TranslateForm(forms.Form):
    source = forms.ChoiceField(label=gettext_lazy("From"))
    targets = forms.MultipleChoiceField(label=gettext_lazy("Into"), widget=forms.CheckboxSelectMultiple, required=True)
    overwrite = forms.BooleanField(
        label=gettext_lazy("Overwrite existing translations"),
        required=False,
        help_text=gettext_lazy(
            "Languages that already exist are replaced by a new translation of the source: the page "
            "fields and all plugins. Changes made in those languages are lost. Leave this off to "
            "translate only the missing languages."
        ),
    )

    def __init__(self, *args, languages: list[dict], source: str, **kwargs):
        super().__init__(*args, **kwargs)
        existing = [lang for lang in languages if lang["exists"]]
        self.fields["source"].choices = [(lang["code"], lang["name"]) for lang in existing]
        self.fields["source"].initial = source
        self.fields["targets"].choices = [(lang["code"], lang["name"]) for lang in languages]
        self.fields["targets"].initial = [lang["code"] for lang in languages if not lang["exists"] and lang["code"] != source]


class ExportForm(forms.Form):
    """Export for translation: the page in one source language, as XLIFF (several languages) or HTML (one)."""

    source = forms.ChoiceField(label=gettext_lazy("From"))
    targets = forms.MultipleChoiceField(label=gettext_lazy("Into"), widget=forms.CheckboxSelectMultiple, required=True)
    format = forms.ChoiceField(
        label=gettext_lazy("File format"),
        widget=forms.RadioSelect,
        initial=files.XLIFF,
        choices=[(files.XLIFF, gettext_lazy("XLIFF 1.2 (for translation tools)")), (files.HTML, gettext_lazy("HTML (one language per file)"))],
    )

    def __init__(self, *args, languages: list[dict], source: str, **kwargs):
        super().__init__(*args, prefix="export", **kwargs)
        self.fields["source"].choices = [(lang["code"], lang["name"]) for lang in languages if lang["exists"]]
        self.fields["source"].initial = source
        self.fields["targets"].choices = [(lang["code"], lang["name"]) for lang in languages]


class ImportForm(forms.Form):
    file = forms.FileField(label=gettext_lazy("Translated file (XLIFF or HTML)"))
    include_changed = forms.BooleanField(label=gettext_lazy("Also import texts whose source changed since the export"), required=False)
    overwrite = forms.BooleanField(label=gettext_lazy("Overwrite existing translations"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, prefix="import", **kwargs)


@admin.register(Translation)
class TranslationAdmin(admin.ModelAdmin):
    list_display = ("created", "page", "source_language", "target_language", "status", "user", "message")
    list_filter = ("status", "target_language")
    search_fields = ("page__pagecontent_set__title", "message")
    date_hierarchy = "created"
    change_list_template = "djangocms_supertext/admin/change_list.html"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_urls(self):
        return [
            path("page/<int:page_id>/", self.admin_site.admin_view(self.translate_view), name="djangocms_supertext_translate"),
            path("page/<int:page_id>/export/", self.admin_site.admin_view(self.export_view), name="djangocms_supertext_export"),
            path("page/<int:page_id>/import/", self.admin_site.admin_view(self.import_view), name="djangocms_supertext_import"),
            path("settings/", self.admin_site.admin_view(self.settings_view), name="djangocms_supertext_settings"),
            # Public on purpose (no admin_view): only echoes the Commando Center's challenge.
            path("ping/", views.ping, name="djangocms_supertext_ping"),
        ] + super().get_urls()

    # -- translate dialog ---------------------------------------------------------------------

    def _page(self, request, page_id: int):
        """The page, if the user may translate it with Supertext (the permission and changing the page)."""
        from cms.models import Page

        if not request.user.has_perm(PERMISSION):
            raise PermissionDenied
        page = get_object_or_404(Page, pk=page_id)
        if not page.has_change_permission(request.user):
            raise PermissionDenied
        return page

    def translate_view(self, request, page_id: int):
        page = self._page(request, page_id)
        options = conf.load()
        languages = translator.describe(page)
        source = request.GET.get("language") or request.POST.get("source") or next((lang["code"] for lang in languages if lang["exists"]), "")
        form = TranslateForm(request.POST or None, languages=languages, source=source)
        results = None
        translated = False

        if request.method == "POST" and form.is_valid():
            try:
                results = translator.translate_page(
                    page,
                    form.cleaned_data["source"],
                    form.cleaned_data["targets"],
                    overwrite=form.cleaned_data["overwrite"],
                    user=request.user,
                    options=options,
                )
            except SupertextError as error:
                form.add_error(None, localized(error))
            else:
                translated = True
                # Start over with the new state: nothing ticked that is translated now.
                languages = translator.describe(page)
                source = form.cleaned_data["source"]
                form = TranslateForm(languages=languages, source=source)

        names = {lang["code"]: lang["name"] for lang in languages}
        response = self._dialog(request, page, options, languages, source, form=form, results=[
            {"result": r, "name": names.get(r.language, r.language), "url": _edit_url(page, r.language)}
            for r in results or []
        ])
        # Version report and key check after the response (an upgrade, a changed key, a rejected key).
        reporting.report_translation(results if translated else [], options, request, response)
        return response

    def _dialog(self, request, page, options, languages, source, *, form=None, export_form=None, import_form=None,
                results=None, export_error="", import_error="", import_results=None):
        context = {
            **self.admin_site.each_context(request),
            "title": _("Translate with Supertext"),
            "page": page,
            "form": form or TranslateForm(languages=languages, source=source),
            "export_form": export_form or ExportForm(languages=languages, source=source),
            "import_form": import_form or ImportForm(),
            "export_url": reverse("admin:djangocms_supertext_export", args=[page.pk]),
            "import_url": reverse("admin:djangocms_supertext_import", args=[page.pk]),
            "export_error": export_error,
            "import_error": import_error,
            "import_results": import_results,
            "max_upload": files.MAX_UPLOAD_BYTES,
            "languages": languages,
            "source": source,
            "configured": bool(options.api_key),
            "signup_url": conf.SIGNUP_URL,
            "api_key_url": conf.API_KEY_URL,
            "results": results or [],
            "is_popup": True,
        }
        return TemplateResponse(request, "djangocms_supertext/translate.html", context)

    # -- translation files ---------------------------------------------------------------------

    def export_view(self, request, page_id: int):
        """Export for translation: answers with the XLIFF or HTML file as a download."""
        page = self._page(request, page_id)
        options = conf.load()
        languages = translator.describe(page)
        source = request.POST.get("export-source") or next((lang["code"] for lang in languages if lang["exists"]), "")
        form = ExportForm(request.POST or None, languages=languages, source=source)
        error = ""
        if request.method == "POST" and form.is_valid():
            try:
                exported = files.export(page, form.cleaned_data["source"], form.cleaned_data["targets"], form.cleaned_data["format"], options)
            except files.FileError as exc:
                error = str(exc)
            else:
                response = HttpResponse(exported.content, content_type=exported.content_type)
                response["Content-Disposition"] = f'attachment; filename="{exported.name}"'
                response["X-Content-Type-Options"] = "nosniff"
                response["Cache-Control"] = "no-store"
                return response
        return self._dialog(request, page, options, languages, source, export_form=form, export_error=error)

    def import_view(self, request, page_id: int):
        """Import translation: reads the uploaded file in memory and writes each job back."""
        page = self._page(request, page_id)
        options = conf.load()
        form = ImportForm(request.POST or None, request.FILES or None)
        error = ""
        results = None
        if request.method == "POST" and form.is_valid():
            upload = form.cleaned_data["file"]
            try:
                files.check_size(upload.size)  # before anything is read
                results = files.import_file(
                    upload.read(),
                    user=request.user,
                    include_changed=form.cleaned_data["include_changed"],
                    overwrite=form.cleaned_data["overwrite"],
                    options=options,
                )
            except files.FileError as exc:
                error = str(exc)
            else:
                form = ImportForm()
        languages = translator.describe(page)
        source = next((lang["code"] for lang in languages if lang["exists"]), "")
        return self._dialog(request, page, options, languages, source, import_form=form, import_error=error,
                            import_results=[_import_lines(r) for r in results] if results is not None else None)

    # -- settings ------------------------------------------------------------------------------

    def settings_view(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied
        from cms.utils.i18n import get_languages
        from django.contrib.sites.models import Site
        from django.shortcuts import redirect

        options = conf.load()
        languages = cms_languages()
        tested = None
        if request.method == "POST" and request.POST.get("action") == "languages":
            errors = save_languages(request, languages, options)
            for error in errors:
                messages.error(request, error)
            if not errors:
                messages.success(request, _("The Supertext languages were saved."))
                return redirect("admin:djangocms_supertext_settings")
            options = conf.load()
        elif request.method == "POST":
            # Test connection: the SDK's key check (ok, invalid, missing, unreachable, error), stored and reported.
            result = reporting.run("test_connection", options, request)
            tested = result.check if result else options.client().check_api_key()
            (messages.success if tested.status == "ok" else messages.error)(request, reporting.check_html(tested))

        sites = []
        for site in Site.objects.order_by("pk"):
            sites.append({"site": site, "languages": [lang["code"] for lang in get_languages(site.pk)]})
        check = tested or reporting.last_check()
        context = {
            **self.admin_site.each_context(request),
            "title": _("Supertext settings"),
            "options": options,
            "sites": sites,
            "languages": [_language_row(options, lang) for lang in languages],
            "target_choices": target_choices(),
            "politeness_targets": _politeness_targets(),
            "signup_url": conf.SIGNUP_URL,
            "api_key_url": conf.API_KEY_URL,
            "opts": self.model._meta,
            "version": plugin_version(),
            "check": check,
            "check_html": reporting.check_html(check) if check else "",
            "checked_at": parse_datetime(check.checked_at) if check else None,
            "reports_enabled": options.reports_enabled,
            "reports_from_environment": options.reports_from_environment,
            "ping_url": (reporting.site_url(options, request) or "") + reporting.ping_path(),
        }
        response = TemplateResponse(request, "djangocms_supertext/settings.html", context)
        if request.method != "POST":
            response_task = lambda: reporting.run("on_request", options, request)  # noqa: E731
            reporting.after_response(response, response_task)
        return response


def _language_row(options: conf.Options, lang: dict) -> dict:
    """One row of the language table: the select's value (override, else saved, else the SDK's
    suggestion, else "— choose —") and whether the language can be translated."""
    code = lang["code"]
    override = options.override_code(code)
    saved = options.saved_code(code)
    suggested = conf.Languages.suggest_target(code) or ""
    selected = override or saved or suggested
    target = options.target_code_or_none(code)
    politeness = options.politeness(code)
    return {
        "code": code,
        "name": lang.get("name", code),
        "sites": lang.get("sites", []),
        "selected": selected,
        "override": override,
        "override_politeness": bool(options.override_politeness(code)),
        "suggested": suggested if not (override or saved) else "",
        "target": target,
        "politeness": politeness,
        "politeness_supported": bool(selected) and conf.Languages.supports_politeness(selected) is True,
        "politeness_unsupported": politeness != "default" and target is not None and conf.Languages.supports_politeness(target) is False,
        "review": options.review(code),
        "override_review": options.override_review(code) is not None,
    }


def _import_lines(result: files.JobResult) -> dict:
    """One job of an import for the dialog: its page, language, error or count lines."""
    counts = result.counts
    lines = []
    if not result.error:
        lines.append(_("Imported: %(count)s") % {"count": counts["ok"]})
        for key, text in (
            ("changed", _("Skipped, source changed since the export: %(count)s")),
            ("untranslated", _("Not translated in the file: %(count)s")),
            ("invalid", _("Formatting changed, not imported: %(count)s")),
            ("missing", _("Not in the file: %(count)s")),
        ):
            if counts[key]:
                lines.append(text % {"count": counts[key]})
    return {"title": result.title, "language": result.language, "error": result.error, "lines": lines}


def _edit_url(page, language: str) -> str:
    content = translator.page_content(page, language)
    if content is None:
        return ""
    try:
        from cms.toolbar.utils import get_object_edit_url

        return get_object_edit_url(content, language)
    except Exception:  # noqa: BLE001 - older django CMS
        return content.get_absolute_url(language)


def translate_url(page, language: str) -> str:
    return reverse("admin:djangocms_supertext_translate", args=[page.pk]) + f"?language={language}"
