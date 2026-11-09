from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Translation(models.Model):
    """One translation of a page into a language (shown in the admin and in the translate dialog)."""

    STATUS_TRANSLATED = "translated"
    STATUS_SKIPPED = "skipped"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_TRANSLATED, _("translated")),
        (STATUS_SKIPPED, _("skipped")),
        (STATUS_ERROR, _("error")),
    ]

    page = models.ForeignKey("cms.Page", on_delete=models.CASCADE, related_name="+", verbose_name=_("page"))
    source_language = models.CharField(_("from"), max_length=15)
    target_language = models.CharField(_("into"), max_length=15)
    status = models.CharField(_("status"), max_length=20, choices=STATUS_CHOICES)
    message = models.TextField(_("message"), blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("user"))
    created = models.DateTimeField(_("date"), auto_now_add=True)

    class Meta:
        verbose_name = _("Supertext translation")
        verbose_name_plural = _("Supertext translations")
        ordering = ["-created"]
        default_permissions = ("view",)
        permissions = [("translate", _("Can translate pages with Supertext"))]

    def __str__(self):
        return f"{self.page} {self.source_language} → {self.target_language}"


class State(models.Model):
    """The plugin's own small key/value store: the version reporter's state (``key = "reporter"``,
    JSON: what was reported last, the latest API key check). Never the API key itself."""

    key = models.CharField(max_length=64, primary_key=True)
    value = models.TextField(blank=True)

    class Meta:
        verbose_name = "Supertext state"
        default_permissions = ()

    def __str__(self):
        return self.key


class LanguageSetting(models.Model):
    """The Supertext language (and form of address) of one django CMS language, chosen on the
    Supertext settings page or in the Django admin. One mapping serves both directions. A code under
    ``LANGUAGES`` in the ``SUPERTEXT`` setting overrides it. ``review``: *Translation review* for
    translations into this language (through the review service)."""

    POLITENESS_CHOICES = [
        ("default", _("Default")),
        ("more", _("Formal (Sie, vous)")),
        ("less", _("Informal (du, tu)")),
    ]

    language = models.CharField(_("django CMS language"), max_length=15, unique=True)
    supertext_code = models.CharField(_("Supertext language"), max_length=32, blank=True)
    politeness = models.CharField(_("form of address"), max_length=10, choices=POLITENESS_CHOICES, default="default")
    review = models.BooleanField(
        _("Translation review"),
        default=False,
        help_text=_(
            "Translations into this language go through Supertext's review service, so reviewers can check and "
            "correct them on the website with the Supertext Localization Review extension. Their corrections are "
            "used the next time the page is translated."
        ),
    )

    class Meta:
        verbose_name = _("Supertext language")
        verbose_name_plural = _("Supertext languages")
        ordering = ["language"]

    def __str__(self):
        return f"{self.language} → {self.supertext_code or '—'}"
