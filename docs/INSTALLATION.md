# Installation guide — Supertext Translation for django CMS

For administrators and developers who install and set up the package. Editors find their part in the [user guide](USER_GUIDE.md).

## Requirements

- django CMS 4.1 or later (tested with 5.1), Django 4.2 or later, Python 3.10 or later (tested up to 3.14)
- More than one language in `LANGUAGES` / `CMS_LANGUAGES`
- [djangocms-text](https://github.com/django-cms/djangocms-text) (or another text plugin with a `body` field) for rich text
- A Supertext account ([log in or create one](https://www.supertext.com/person/en/account/signin)) and an API key from [supertext.com → Integrations → API](https://www.supertext.com/en/integrations/api) (see [API key](#api-key))
- The server must reach `https://api.supertext.com` over HTTPS (and, for [Translation review](#translation-review), Supertext's review service)

## Install

```bash
pip install git+https://github.com/Supertext/djangoCMS-Supertext-Translation.git
```

(Publishing to PyPI as `djangocms-supertext-translation` is planned.)

Add the app and migrate:

```python
# settings.py
INSTALLED_APPS = [
    ...,
    "djangocms_supertext",
    "cms",
    ...,
]
```

```bash
python manage.py migrate djangocms_supertext
```

No URLs need to be added: the package's pages live in the Django admin. It adds:

- *Translate with Supertext…* to the django CMS toolbar's **Language** menu (edit mode),
- *Supertext → Supertext translations* in the admin (a log of all translations) with *Settings and connection* for superusers,
- the management commands `supertext_translate` and `supertext_check`,
- a public ping endpoint for Supertext's reachability check (see [Version information and the API key check](#version-information-and-the-api-key-check)).

Optional: if your admin isn't reachable from the internet (an IP allowlist, a VPN), give the ping endpoint a public address outside the admin:

```python
# urls.py (inside or outside i18n_patterns)
urlpatterns += [path("supertext/", include("djangocms_supertext.urls"))]   # → /supertext/ping
```

### Update

```bash
pip install --upgrade git+https://github.com/Supertext/djangoCMS-Supertext-Translation.git
python manage.py migrate djangocms_supertext
```

See [CHANGELOG.md](../CHANGELOG.md).

### Uninstall

Remove `"djangocms_supertext"` from `INSTALLED_APPS` after running `python manage.py migrate djangocms_supertext zero` (which drops the translation log, the chosen Supertext languages and the package's state table), then `pip uninstall djangocms-supertext-translation`. Translations already made are normal page content and stay.

## API key

1. **No Supertext account yet?** [Create one at supertext.com](https://www.supertext.com/person/en/account/signin) (the same page logs you in if you already have one; you sign in with your email address).
2. **Generate the API key** at [supertext.com → Integrations → API](https://www.supertext.com/en/integrations/api). Only users with the **Admin** role in the Supertext account can do this; otherwise ask your account's admin.

Set the key as an environment variable of the server:

```bash
SUPERTEXT_API_KEY="your-key"
```

You can paste it with or without the `Supertext-Auth-Key ` prefix that Supertext shows; the package sends it as `Authorization: Supertext-Auth-Key <key>`. Alternatively set `"API_KEY"` in the `SUPERTEXT` setting (below); the environment variable wins. Keep the key out of your repository.

The package checks the key automatically (see [Version information and the API key check](#version-information-and-the-api-key-check)) and shows the latest result on the settings page: *Supertext → Supertext translations → Settings and connection* (superusers). **Test connection** there, or `python manage.py supertext_check`, checks it again. Both call a cost-free endpoint of the Supertext API. While no key is set or Supertext rejects it, the settings page, the translate dialog and `supertext_check` link to the account signup and the API key page. The settings page also shows the installed *Plugin version* (django CMS doesn't list app versions in its admin); a release version links to its release notes on GitHub.

![The Supertext settings page: "API key checked: the connection to Supertext works." with its time, the API key's source, the live API address, the review service address, the timeout, the plugin version, links to create a Supertext account and to generate the API key, Send version information to Supertext: On with the ping address, and the Languages table with a Supertext language select and a form of address and a Translation review checkbox per django CMS language](images/06-settings.png)

## Languages

The package translates between the languages django CMS is configured with (`LANGUAGES` and `CMS_LANGUAGES` per site), e.g.:

```python
LANGUAGES = [
    ("en", "English"),
    ("de-ch", "Deutsch (Schweiz)"),
    ("fr-ch", "Français (Suisse)"),
    ("it-ch", "Italiano (Svizzera)"),
]
```

Each django CMS language needs a Supertext language. **Choose it on the settings page** (*Django admin → Supertext → Supertext translations → Settings and connection → Languages*, superusers): one row per django CMS language (of all sites, the source language included), with a select of all Supertext languages ("Name (code)"), where Supertext offers it for the chosen language the form of address, and the **Translation review** checkbox (off by default, see [Translation review](#translation-review)). *Save languages* stores the choices in the database (table `djangocms_supertext_languagesetting`, migrations `0003_language_setting` and `0004_language_review`); only codes from Supertext's list are accepted. One choice serves both directions: a language chosen as `de-CH` is translated into `de-CH` and from `de`.

![The Languages table on the Supertext settings page: English en with "English (United States) (en-US)" preselected as a suggestion and "No choice for this language" as form of address; Deutsch (Schweiz), Français (Suisse) and Italiano (Svizzera) with German, French and Italian (Switzerland) and "Formal (Sie, vous)"; a Translation review checkbox per language, not ticked, with its explanation below the table; the Save languages button](images/08-languages.png)

Supertext accepts exactly these target codes (from its `features` list, October 2026), which is what the select offers:

| Language | Supertext codes |
| --- | --- |
| German, English, French, Italian, Portuguese | `de-DE`, `de-CH`, `de-AT`, `en-US`, `en-GB`, `fr-FR`, `fr-CH`, `it-IT`, `it-CH`, `pt-PT`, `pt-BR` |
| Chinese, Serbian | `zh-Hans`, `zh-Hant`, `sr-Latn`, `sr-Cyrl` |
| Swiss German | `gsw-u-sd-chzh` (Zurich), `gsw-u-sd-chbe` (Bern) |
| All others, without region | `bg`, `cs`, `da`, `el`, `es`, `fi`, `hr`, `hu`, `ja`, `ko`, `nb`, `nl`, `pl`, `rm`, `ru`, `sk`, `sl`, `sq`, `sv`, `tr` |

A language nobody has chosen a Supertext language for is translated with the **suggestion** the select shows preselected (the Supertext SDK's default), so obvious languages work without any setup:

| django CMS code | Supertext language used until you choose another one |
| --- | --- |
| a Supertext code apart from case and `_`/`-` | that code: `de-ch` → `de-CH`, `fr_ch` → `fr-CH`, `es`, `nl`, `zh-hant` → `zh-Hant` |
| `de`, `en`, `fr`, `it`, `pt` | `de-DE`, `en-US`, `fr-FR`, `it-IT`, `pt-PT` |
| `zh`, `zh-cn`, `zh-sg` / `zh-tw`, `zh-hk`, `zh-mo` | `zh-Hans` / `zh-Hant` |
| `sr` | `sr-Latn` |
| a region of a language Supertext has without region | the bare code: `es-es` → `es`, `sl-si` → `sl`, `nl-be` → `nl` |
| anything else (`en-ie`, `de-li`, `gsw`, `sr-rs`, `no`, …) | none: the select shows *— choose —* and the row is marked; until you choose one, translating into it is reported as *has no Supertext language yet* and nothing is sent for it |

- Choose another language where the suggestion isn't what your site means, e.g. `de-CH` for a `de` site in Switzerland, `en-GB` for British English, `nb` for `no`.
- The source language is sent without region (`en-gb` → `en`; `de` chosen as `de-CH` translates from `de`).
- Formal/informal is only offered where Supertext has it (not for English, Swiss German, Romansh, Albanian and Serbian).
- **Override for automated setups:** a `code` (and/or `politeness`, `review`) under `SUPERTEXT["LANGUAGES"]` in the settings (below) wins over the settings page. That row's select (or checkbox) is then disabled and says *Set under LANGUAGES in the SUPERTEXT setting*. Sites that configured `LANGUAGES` before keep working unchanged; to manage a language on the settings page instead, remove its entry from `LANGUAGES`.

The editors see the languages in the toolbar's *Language* menu:

![The django CMS toolbar in edit mode with the Language menu open: English, Add Translation, Delete Translation and "Translate with Supertext…"](images/01-language-menu.png)

## Permissions

Editors need:

- **djangocms_supertext | Supertext translation | Can translate pages with Supertext** (`djangocms_supertext.translate`)
- permission to change the page (with `CMS_PERMISSION = True`, django CMS's page permissions; otherwise the model permissions `cms.change_page`, `cms.add_pagecontent`, `cms.change_pagecontent`)
- the permissions of the plugins on the page (e.g. `djangocms_text | text | Can add/change/delete text`), because translating copies the plugins into the target language

*Export for translation* and *Import translation* (in the translate dialog) need the same permissions; an import is refused for pages the user may not change. They need no API key and have nothing to configure. Uploads are limited to 10 MB (Django's `DATA_UPLOAD_MAX_MEMORY_SIZE` doesn't apply to files; your web server's request size limit must allow 10 MB for the full limit) and are read in memory, never stored.

Superusers additionally see the settings page. The log (*Supertext translations*) is visible with `djangocms_supertext.view_translation`.

## Settings

All settings are optional and go in one dict:

```python
SUPERTEXT = {
    "API_KEY": "",                    # or the SUPERTEXT_API_KEY environment variable (wins)
    "ENVIRONMENT": "live",            # live | staging | testing
    "API_URL": "",                    # custom base URL; or SUPERTEXT_API_URL (wins)
    "REVIEW_URL": "https://localizationreview-production.up.railway.app/v1/",  # the default; "" = Translation review off
    "LANGUAGES": {                    # optional: overrides the settings page's Languages table
        "de-ch": {"politeness": "more", "review": True},  # formal (Sie, vous), Translation review on
        "fr": {"code": "fr-CH", "politeness": "less"},  # other Supertext code, informal (du, tu)
    },
    "TIMEOUT": 180,                   # seconds to wait for one language
    "PLUGIN_FIELDS": {                # more plugin fields to translate (merged with the defaults)
        "HeroPlugin": {"heading": "text", "content": "html"},
    },
    "VERSION_REPORTS": True,          # "Send version information to Supertext"; SUPERTEXT_VERSION_REPORTS=0 (wins)
    "SITE_URL": "",                   # the site's public address for version reports, e.g. "https://www.example.ch"
}
```

| Key | Default | Description |
| --- | --- | --- |
| `API_KEY` | – | Supertext API key; the environment variable `SUPERTEXT_API_KEY` takes precedence. |
| `ENVIRONMENT` | `live` | `live` (`https://api.supertext.com/v1/`), `staging` or `testing`. |
| `API_URL` | – | A different base URL (test server); `SUPERTEXT_API_URL` takes precedence. For [Translation review](#translation-review) use the Languages table's checkbox instead. |
| `REVIEW_URL` | Supertext's review service | Address of the review service for languages with *Translation review* on (see [Translation review](#translation-review)). `""` turns review off for every language. The environment variable `SUPERTEXT_REVIEW_URL` takes precedence when set. Only change it when Supertext gives you another address. |
| `LANGUAGES` | `{}` | Optional override of the settings page's [Languages](#languages) table, for automated setups. Per django CMS language code: `code`, the Supertext language (one of the [Supertext codes](#languages), e.g. `de-CH`, `es`, `zh-Hans`; as source its language without region is sent), `politeness`: `more` formal, `less` informal, `default` (only for languages that offer it), and `review`: `True`/`False` for *Translation review* into this language. A value set here wins over the settings page, whose select or checkbox for it is then disabled. |
| `TIMEOUT` | `180` | Seconds to wait for the translation of one language. |
| `POLL_INTERVAL` | `2` | Seconds between status checks. |
| `PLUGIN_FIELDS` | see below | Plugin type → `{model field: "text" or "html"}`. |
| `VERSION_REPORTS` | `True` | **Send version information to Supertext** (see below). `False` turns it off; the environment variable `SUPERTEXT_VERSION_REPORTS` (`0`/`false`/`off`/`no` or `1`/`true`/`on`/`yes`) takes precedence. |
| `SITE_URL` | – | The site's public base URL sent with version reports and used for the ping address. Default: the address of the admin request (scheme and host); commands use the Django site's domain (not `example.com`). |

**Plugins translated out of the box:** `TextPlugin` (`body`, HTML; djangocms-text and djangocms-text-ckeditor), `LinkPlugin` (`name`; djangocms-link), `PicturePlugin` (`caption_text`), `FilePlugin` (`file_name`), `VideoPlayerPlugin` (`label`). Add your own plugins with `PLUGIN_FIELDS`; all other plugins are copied into the new language unchanged.

## Translation review

With **Translation review**, people check the translations on the website itself and correct them there: customers or Supertext linguists open the original and the translated page side by side in Chrome with the *Supertext Localization Review* extension and fix texts in a side panel. Their corrections come back into django CMS.

Turn it on per language that is translated **into**: *Django admin → Supertext → Supertext translations → Settings and connection → Languages*, tick **Translation review** in that language's row (e.g. *Deutsch (Schweiz)*) → *Save languages*. Untick it to turn it off again; nothing else changes. (Or `"review": True` for that language under `SUPERTEXT["LANGUAGES"]`, which wins over the checkbox.)

- Translations into that language then go through Supertext's review service instead of directly to Supertext. It answers exactly like Supertext and passes everything on with your API key, so billing, languages, formal/informal and error messages stay the same.
- The review service keeps every translation of your account. A text it has translated before gets the same translation again (without a new Supertext call), and once a reviewer has corrected it, the corrected text.
- **Corrections arrive with the next translation:** after a review, translate the page into that language again (*Translate with Supertext…* with *Overwrite existing translations*) to write the corrections into django CMS. As always, overwriting replaces manual changes in the translated texts.
- Reviewers get a review link for your site from Supertext; nothing to set up in django CMS.
- The review service works with keys of the **live** Supertext API. With `ENVIRONMENT` `staging` or `testing` (or `API_URL`), leave review off.
- *Export for translation* and *Import translation* don't use the review service. The API key check (*Test connection*) and the version reports still go directly to Supertext.
- The settings page shows the review service's address under *Connection* (*Review service*), or *Off* when `REVIEW_URL` is empty; the checkboxes are then disabled.

## Version information and the API key check

**Send version information to Supertext** is on by default. The package then tells Supertext which version runs where, after an update and when the API key check result changes, so Supertext support can see which version you run. A report contains exactly: the site URL (`SITE_URL`, else the address of the admin request), the package's name and version, the django CMS and Python versions, the Supertext SDK version, whether a key is set, the result of the API key check below (status, time, HTTP status, Supertext's error code) and the address of the ping endpoint. **No content, no API key and no personal data are sent.** Reports go from the server (after the admin page has been sent, so they never slow it down), never from the browser; a report that fails is not retried for an hour and never breaks a page or a translation. `supertext_check` sends one report on demand. Turn it off with `"VERSION_REPORTS": False` in `SUPERTEXT` or the environment variable `SUPERTEXT_VERSION_REPORTS=0`: nothing is sent at all then, and the ping endpoint answers 404. The settings page shows whether it's on.

**The API key check** runs whether or not version information is sent: when the package's admin pages or commands run with a key it hasn't checked yet (the key is compared by a fingerprint stored in the database, never the key itself), on **Test connection**, in `supertext_check`, and when Supertext rejects the key during a translation. It's Supertext's cost-free `features` call; nothing is translated or billed. The settings page shows the latest result with its time: *the connection works*, *Supertext rejected the API key* or *no API key is set* (both with the links to create an account and generate a key), *Supertext can't be reached* or *Supertext answered with an error*.

**The ping endpoint** `GET <site>/<admin>/djangocms_supertext/translation/ping/?challenge=…` (or `/supertext/ping` with the optional URL include above; the settings page shows the address) is public (no login, no session) and answers only `{"ok":true,"plugin":"djangoCMS-Supertext-Translation","challenge":"…"}` with `Cache-Control: no-store`, so Supertext can see that the site is reachable from the internet. It returns nothing else: no versions, no settings, no data.

The package keeps this state (what was reported last, the latest key check) in its table `djangocms_supertext_state` (migration `0002_state`).

## Interface languages

The *Translate with Supertext* dialog, the settings page, the translation log and all Supertext messages are available in English, German, French and Italian. They follow each user's django CMS interface language: *site name menu → User settings → Language* in the toolbar, otherwise the browser's language through Django's `LocaleMiddleware`. A language is only offered if it is in your `LANGUAGES` setting; other languages fall back to English. The `manage.py` commands print English, and the permission name stays English too (Django stores permission names in the database when it migrates).

## Request timeouts

Translating runs in the editor's request: a few seconds per language, up to `TIMEOUT` for very long pages. Make sure your web server and proxy allow that (e.g. gunicorn `--timeout 300`).

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| No *Translate with Supertext…* in the Language menu | The toolbar isn't in edit mode, the app isn't in `INSTALLED_APPS`, or the user lacks `djangocms_supertext.translate` or permission to change the page. |
| *Supertext is not set up yet* in the dialog | `SUPERTEXT_API_KEY` is not set on the server. Generate a key at [supertext.com → Integrations → API](https://www.supertext.com/en/integrations/api) (Admin role) and set it. |
| *Authentication failed. Please check the Supertext API key.* | Wrong or revoked key, or a key for another environment. Generate a new one at [supertext.com → Integrations → API](https://www.supertext.com/en/integrations/api) (Admin role) and use *Test connection*. |
| *This language is published. Create a draft of it, then translate again.* | With djangocms-versioning, only drafts can be changed. Create a draft of that language (or delete the language) and translate again. |
| *The language … has no Supertext language yet* / *No Supertext language: choose one* on the settings page | The django CMS code isn't a Supertext code and has no default (e.g. `en-ie`, `gsw`): choose its Supertext language under *Supertext → Supertext translations → Settings and connection → Languages* (see [Languages](#languages)). |
| *Supertext does not support this language pair (en → xx-YY)* | A `code` in `SUPERTEXT["LANGUAGES"]` Supertext doesn't offer (e.g. `es-ES` instead of `es`), or the same language as source and target. Fix it (or remove it and choose the language on the settings page); the message shows the codes that were sent. |
| *Supertext offers no formal or informal tone for this language* | `politeness` under `SUPERTEXT["LANGUAGES"]` is `more`/`less` for a language without it (English, Swiss German, Romansh, Albanian, Serbian); remove it. Nothing is sent for that language until then. |
| *Supertext rejected the API key* on the settings page | The key is wrong or revoked. Check that the whole key was copied into `SUPERTEXT_API_KEY`, or generate a new one at [supertext.com → Integrations → API](https://www.supertext.com/en/integrations/api) (Admin role). No Supertext account yet? [Create one at supertext.com](https://www.supertext.com/person/en/account/signin). Then *Test connection*. |
| *The API key couldn't be checked because Supertext can't be reached* | The server can't reach `api.supertext.com` (firewall, proxy, DNS). Translations need the same connection. |
| *Too many requests to Supertext* | The API's per-second limit was hit repeatedly although the package retries. Try again shortly. |
| *Timed out waiting for the Supertext translation* or a 502/504 from the proxy | Very long page: raise `TIMEOUT` and the web server's request timeout. |
| A plugin's text stays in the source language | Its plugin type isn't in `PLUGIN_FIELDS`. Add it. |
| *Your Supertext translation limit is exceeded.* | The Supertext subscription's quota is used up. |
| *Authentication failed* only for languages with *Translation review* | The review service only works with keys of the live Supertext API: with `ENVIRONMENT` `staging`/`testing` (or `API_URL`) leave review off. |
| Reviewers' corrections don't show up in django CMS | They arrive with the next translation: translate the page into that language again with *Overwrite existing translations*. Check that the language's *Translation review* is ticked. |
| No *Translation review* column / *no such column: review* | Run `python manage.py migrate djangocms_supertext` (migration `0004_language_review`). |

Errors are also logged (logger `djangocms_supertext`). More technical details are in the [developer guide](DEVELOPER.md).
