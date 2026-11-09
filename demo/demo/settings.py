"""Settings of the Supertext django CMS demo. Everything secret or deployment-specific comes from
environment variables (Railway service variables); see .env.example."""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or "insecure-local-development-key"
DEBUG = os.environ.get("DJANGO_DEBUG", "") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    CSRF_TRUSTED_ORIGINS.append("https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"])

INSTALLED_APPS = [
    "site_setup",
    "djangocms_supertext",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "cms",
    "menus",
    "treebeard",
    "sekizai",
    "djangocms_text",
]

MIDDLEWARE = [
    "cms.middleware.utils.ApphookReloadMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "cms.middleware.user.CurrentUserMiddleware",
    "cms.middleware.page.CurrentPageMiddleware",
    "cms.middleware.toolbar.ToolbarMiddleware",
    "cms.middleware.language.LanguageCookieMiddleware",
]

ROOT_URLCONF = "demo.urls"
WSGI_APPLICATION = "demo.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "sekizai.context_processors.sekizai",
                "cms.context_processors.cms_settings",
            ]
        },
    }
]


def database():
    """DATABASE_URL points at the PostgreSQL server; the demo uses its own database on it."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
    config = dj_database_url.parse(url, conn_max_age=60)
    config["NAME"] = os.environ.get("DJANGOCMS_DB_NAME", "djangocms")
    return config


DATABASES = {"default": database()}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Languages: English source, Swiss German, French and Italian
LANGUAGE_CODE = "en"
TIME_ZONE = "Europe/Zurich"
USE_I18N = True
USE_TZ = True
LANGUAGES = [
    ("en", "English"),
    ("de-ch", "Deutsch (Schweiz)"),
    ("fr-ch", "Français (Suisse)"),
    ("it-ch", "Italiano (Svizzera)"),
]

SITE_ID = 1
CMS_CONFIRM_VERSION4 = True
CMS_PERMISSION = False  # Django's model permissions are enough for the demo's Editors group
CMS_TEMPLATES = [("page.html", "Page")]
CMS_LANGUAGES = {
    SITE_ID: [
        {"code": code, "name": name, "public": True, "hide_untranslated": True, "redirect_on_fallback": False}
        for code, name in LANGUAGES
    ],
    "default": {"fallbacks": ["en"], "public": True, "hide_untranslated": True},
}
X_FRAME_OPTIONS = "SAMEORIGIN"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Supertext. The key comes from SUPERTEXT_API_KEY (and SUPERTEXT_API_URL, if set). The Supertext
# languages are chosen on the settings page (demo_setup preselects a formal tone for the targets;
# en uses the SDK's default en-US), so LANGUAGES isn't set here.
SUPERTEXT = {
    # Version reports: the public address (SUPERTEXT_VERSION_REPORTS=0 turns them off).
    "SITE_URL": "https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"] if os.environ.get("RAILWAY_PUBLIC_DOMAIN") else "",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}
SILENCED_SYSTEM_CHECKS = ["treebeard.E001"]  # django CMS 5.1 with treebeard 5
