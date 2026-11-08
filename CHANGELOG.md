# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/).

## Unreleased

### Added

- Docs: demo movie in the README (`docs/images/demo.gif`, recorded from the demo against the stand-in with `tests/docs/movie.mjs`; the MP4 version, not committed, is narrated with the Piper voice “alba”) and an install and configuration movie (`tests/docs/movie-install.mjs`: pip install, `INSTALLED_APPS` and `LANGUAGES`, `migrate`, `SUPERTEXT_API_KEY` and `supertext_check`, then *Settings and connection* with *Test connection* and the Languages table; narrated MP4, not committed). The stand-in can keep files `in_progress` for a while (`STAND_IN_DELAY`).
- **Translation review** on/off per language (*Supertext → Supertext translations → Settings and connection → Languages*, column *Translation review*; or `review` under `SUPERTEXT["LANGUAGES"]`): translations into a language with *Translation review* ticked go through Supertext's review service (Supertext Localization Review), where customers and Supertext linguists correct them on the website with a Chrome extension; corrections come back into django CMS with the next translation, and texts translated before keep their (reviewed) wording. Same API key, billing, languages and messages; other languages keep going directly to Supertext. New setting `REVIEW_URL` / `SUPERTEXT_REVIEW_URL` (defaults to Supertext's review service; `""` turns review off everywhere), shown on the settings page. Migration `0004_language_review` (run `python manage.py migrate djangocms_supertext`; existing languages start with review off). All four interface languages.
- Requests to Supertext name the plugin's repository and version in the User-Agent (`djangoCMS-Supertext-Translation/<version>`, before `djangocms-supertext-translation/<version>`).
- **Export for translation (XLIFF 1.2 or HTML) and import of translated files**; Supertext SDK 0.5.0. In the *Translate with Supertext* dialog, *Export for translation* downloads the page's texts as an XLIFF file (one or more languages, for translation tools) or an HTML file (one language, e.g. for Supertext's web app); *Import translation* reads the translated file back and creates the language like an API translation (existing languages only with *Overwrite existing translations*, drafts with djangocms-versioning; texts whose source changed since the export only with *Also import texts whose source changed since the export*), with a summary per page and language. Same permissions as translating, files up to 10 MB, nothing stored on the server. In English, German, French and Italian.
- **Supertext languages on the settings page:** *Supertext → Supertext translations → Settings and connection → Languages* has a select per django CMS language (all sites, source language included) with Supertext's languages as "Name (code)", and the form of address where Supertext offers it; *Save languages* stores them (new table, migration `0003_language_setting`: run `python manage.py migrate djangocms_supertext` after updating). The select preselects the saved language, else Supertext's suggestion (`de` → `de-DE`, `en` → `en-US`, `es-es` → `es`, `zh-tw` → `zh-Hant`), else *— choose —*. `SUPERTEXT["LANGUAGES"]` stays as an optional override: what is set there keeps working unchanged, wins, and its select is disabled with a note. In English, German, French and Italian.
- Support for Python 3.14 (tested in CI with django CMS 5.1 and Django 6).
- Automatic API key check: when the key is new or changed, on *Test connection*, in `supertext_check` and when Supertext rejects the key during a translation. The settings page shows the latest result with its time (*the connection works*, *rejected*, *no key*, *Supertext can't be reached*, *error*), with links to create an account and generate a key, in English, German, French and Italian.
- *Send version information to Supertext* (on by default; `"VERSION_REPORTS": False` in `SUPERTEXT` or `SUPERTEXT_VERSION_REPORTS=0` turns it off): after an update and when the key check result changes, the package sends the site URL, the package, django CMS, Python and SDK versions, whether a key is set, the key check result and the ping address to Supertext. No content, no API key and no personal data. Shown on the settings page. New option `SITE_URL` for the site's public address.
- Public ping endpoint `<admin>/djangocms_supertext/translation/ping/` (optionally `/supertext/ping` with `include("djangocms_supertext.urls")`) that only echoes Supertext's challenge, so Supertext can check the site is reachable (404 with version reports off).
- New table for this state (migration `0002_state`): run `python manage.py migrate djangocms_supertext` after updating.
- Messages for a language without a Supertext language (*has no Supertext language yet*) and for a formal/informal tone Supertext doesn't offer for a language, in all four languages. The settings page marks languages that have no Supertext language and no default, and warns about such a tone.

- Its own message for an unsupported language pair, naming the codes ("Supertext does not support this language pair (en → xx-YY)"), in English, German, French and Italian.
- French and Italian interface (and German where it was missing): the dialog, settings page, log and all Supertext error messages follow the user's interface language.
- The settings page shows the installed plugin version, linked to its release notes on GitHub.
- Support: the Supertext support form is linked in the README, the user guide and GitHub's "New issue" page.

### Changed

- **Languages are no longer guessed beyond the obvious.** The Supertext language chosen on the settings page (or under `SUPERTEXT["LANGUAGES"]`) wins; else a django CMS language code that is a Supertext code (`de-ch`, `fr-ch`, `es`, `zh-hans`, apart from case and `_`/`-`) is used as it is; else the Supertext SDK's default (`de` → `de-DE`, `en` → `en-US`, `fr` → `fr-FR`, `it` → `it-IT`, `pt` → `pt-PT`, `zh-cn` → `zh-Hans`, `zh-tw` → `zh-Hant`, `sr` → `sr-Latn`, `es-es` → `es`, `sl-si` → `sl`). The old default regions are gone: they were wrong for many languages (Supertext wants `es`, `sl`, `nl` without region, `zh-Hans` instead of `zh-CN`). A language without any of these (`en-ie`, `gsw`, `no`) is reported ("choose it on the settings page") and nothing is sent for it. A formal/informal tone for a language without it is reported instead of being sent.
- *Test connection* shows the key check result (also for a rejected key) instead of *Connected. The API key works.*; `supertext_check` also sends a version report and prints the plugin version.
- All Supertext API calls now go through the official Supertext Python SDK (0.2.0, commit `c66cb4d`, `v1` namespace), shipped inside the package (nothing extra to install). The `beautifulsoup4` dependency is gone.

### Changed

- Supertext SDK updated to 0.4.0 (commit `6aaad33`): default target languages, `suggest_target()` and `target_options()` for the settings page.
- The demo chooses its Supertext languages on the settings page (`demo_setup`) instead of `SUPERTEXT["LANGUAGES"]`.
- Version reports, the API key check result and the reachability ping now use Supertext Plugin Health 0.1.0 (bundled in `djangocms_supertext/_vendor/plugin_health`); Supertext SDK updated to 0.3.0 (commit `f7bd414`). No change for sites: settings and stored state stay as they are.
- The "No Supertext API key" and "Authentication failed" messages from the API client now link to account signup and API key generation.

### Fixed

- Supertext SDK 0.2.1 (commit `eeba8fa`): one `LANGUAGES` mapping serves both directions. A mapped language is sent as a source in its source form (`"de": {"code": "de-CH"}` translates from `de`), so English as the source no longer fails with an `en-US` mapping.

## 0.1.0 — 2026-10-07

### Added

- First version for django CMS 4.1 and later.
- *Translate with Supertext…* in the toolbar's Language menu: a dialog to translate the page from one language into others, with "Already translated" / "Translated with Supertext on …" per language and an explicit *Overwrite existing translations* option.
- Translates the page title, page title, menu title and meta description, and the texts of the page's plugins: Text (as HTML, markup kept), Link, Picture, File and Video plugins out of the box, more via `SUPERTEXT["PLUGIN_FIELDS"]`. Plugins are copied into the new language; inline plugins in text bodies are relinked.
- New languages get a slug from the translated title; with djangocms-versioning they are created as drafts, and published languages are not overwritten.
- Permission *Can translate pages with Supertext*; page change permissions apply.
- Admin: a log of all Supertext translations and a settings page with *Test connection* (superusers).
- The settings page, the "not set up yet" notice in the translate dialog and `supertext_check` link to the Supertext account signup and to supertext.com → Integrations → API, where users with the Admin role generate the API key. Installation guide and README explain the same.
- Settings: `SUPERTEXT_API_KEY` (with or without the `Supertext-Auth-Key` prefix), `SUPERTEXT_API_URL`, and the `SUPERTEXT` setting (environment, languages and tone, timeout, plugin fields).
- Management commands `supertext_translate` and `supertext_check`.
- Retries when the Supertext API answers HTTP 429 (rate limit).
- German admin strings.
- Demo for Railway (`demo/`) with demo accounts, an Editors group and English sample pages created on every start.
