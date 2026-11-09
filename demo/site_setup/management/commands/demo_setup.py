"""
Demo setup, run on every start (idempotent: only adds what is missing, never changes existing
accounts or content):

- the DEMO_ADMIN_* (superuser) and DEMO_EDITOR_* (Editors group) accounts
- the Editors group: pages, page contents and text plugins in every language, Supertext
- an English home page and the sample article "Swiss chocolate, shipped worldwide"
- the Supertext languages of the target languages (de-CH, fr-CH, it-CH, formal) on the settings page,
  for languages nobody has chosen yet (English uses the SDK's default en-US)

Passwords are never printed; only variable names.
"""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

HOME = {
    "title": "Welcome",
    "meta_description": "A django CMS demo site translated with Supertext.",
    "body": (
        "<p>This site was written in <strong>English</strong>. Open a page, switch to edit mode and choose "
        "<em>Language → Translate with Supertext…</em> to create the German, French and Italian versions.</p>"
    ),
}

ARTICLE = {
    "title": "Swiss chocolate, shipped worldwide",
    "meta_description": "How a small family business in Bern brings handmade pralines to 40 countries.",
    "body": (
        "<h2>From Bern to the world</h2>"
        "<p>Every praline is made by hand in our <strong>Bern</strong> workshop. "
        'Read more on <a href="https://www.supertext.com">our website</a>.</p>'
        "<ul><li>Fresh ingredients from local farmers</li><li>Climate-neutral delivery within 48 hours</li></ul>"
    ),
}


class Command(BaseCommand):
    help = "Creates the demo accounts, the Editors group and the sample pages if they are missing."

    def handle(self, *args, **options):
        self.ensure_site()
        group = self.ensure_editors_group()
        self.ensure_accounts(group)
        self.ensure_pages()
        self.ensure_supertext_languages()

    def log(self, message):
        self.stdout.write(f"[demo] {message}")

    def ensure_supertext_languages(self):
        from djangocms_supertext.models import LanguageSetting

        for language, code in (("de-ch", "de-CH"), ("fr-ch", "fr-CH"), ("it-ch", "it-CH")):
            _, created = LanguageSetting.objects.get_or_create(language=language, defaults={"supertext_code": code, "politeness": "more"})
            if created:
                self.log(f"Supertext language for {language}: {code}, formal")

    def ensure_site(self):
        domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "localhost:8000"
        site = Site.objects.get_current()
        if site.name != "Supertext django CMS Demo" or site.domain != domain:
            site.name, site.domain = "Supertext django CMS Demo", domain
            site.save()

    def ensure_editors_group(self):
        group, created = Group.objects.get_or_create(name="Editors")
        if created:
            perms = Permission.objects.filter(
                Q(content_type__app_label="cms", codename__in=[
                    "view_page", "add_page", "change_page", "publish_page",
                    "view_pagecontent", "add_pagecontent", "change_pagecontent", "delete_pagecontent",
                    "view_placeholder", "use_structure",
                ])
                | Q(content_type__app_label="djangocms_text")
                | Q(content_type__app_label="djangocms_supertext", codename__in=["translate", "view_translation"])
            )
            group.permissions.set(perms)
            self.log("Editors group created.")
        return group

    def ensure_accounts(self, editors):
        User = get_user_model()
        for prefix, superuser in (("DEMO_ADMIN", True), ("DEMO_EDITOR", False)):
            email = os.environ.get(f"{prefix}_EMAIL", "").strip()
            password = os.environ.get(f"{prefix}_PASSWORD", "")
            if not email or not password:
                self.log(f"{prefix}_EMAIL / {prefix}_PASSWORD not set; skipping that account.")
                continue
            if User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
                self.log(f"{prefix}: account exists, left unchanged.")
                continue
            candidate = User(username=email, email=email)
            try:
                validate_password(password, candidate)
            except ValidationError as error:
                self.stderr.write(f"[demo] WARNING: {prefix}_PASSWORD does not meet Django's password rules ({' '.join(error.messages)}); account not created.")
                continue
            user = User.objects.create_user(username=email, email=email, password=password, is_staff=True,
                                            is_superuser=superuser, first_name="Demo", last_name="Admin" if superuser else "Editor")
            if not superuser:
                user.groups.add(editors)
            self.log(f"{prefix}: account created.")

    @transaction.atomic
    def ensure_pages(self):
        from cms.api import create_page
        from cms.models import Page

        if Page.objects.exists():
            return
        home = create_page(HOME["title"], "page.html", "en", meta_description=HOME["meta_description"], in_navigation=True,
                           created_by="demo")
        home.set_as_homepage()
        self.add_text(home, HOME["body"])
        article = create_page(ARTICLE["title"], "page.html", "en", parent=home, meta_description=ARTICLE["meta_description"],
                              menu_title="Swiss chocolate", in_navigation=True, created_by="demo")
        self.add_text(article, ARTICLE["body"])
        self.log("Sample pages created (English).")

    def add_text(self, page, body):
        from cms.api import add_plugin

        content = page.get_admin_content("en")
        placeholder = content.rescan_placeholders()["content"]
        add_plugin(placeholder, "TextPlugin", "en", body=body)
