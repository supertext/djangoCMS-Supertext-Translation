# Developer guide — Supertext Translation for django CMS

How the package is built, how to work on it, and how it is released and deployed.

## Architecture

A Django app (`djangocms_supertext`, package `djangocms-supertext-translation`) for django CMS 4.1+ (page contents per language, placeholders per page content).

```
Toolbar (edit mode): Language → "Translate with Supertext…"        cms_toolbars.py
   │ modal: GET/POST /admin/djangocms_supertext/translation/page/<page_id>/     admin.py (translate_view)
   │ needs djangocms_supertext.translate and permission to change the page
   ▼
translator.translate_page(page, source, targets, overwrite, user)
   │ _collect(): PageContent fields + configured plugin fields of the source's placeholders
   │ per target: skip if it exists (unless overwrite); with djangocms-versioning only drafts
   │ document.build(): one <div data-st-id="N"> per value; chunks below 900k characters
   ▼
client.SupertextClient   POST file → poll status → GET translation → DELETE   (requests)
   ▼
_apply(): create_page_content() (new language) or update the fields; replace the target's plugins with
          copies of the source's (copy_plugins_to_placeholder), set the translated fields (inline plugin
          ids in text bodies remapped); Translation rows as the log
```

| Module | Responsibility |
| --- | --- |
| `client.py` | Wrapper around the bundled Supertext SDK (`_vendor/supertext`): requests through `requests`, segments packed into documents below the size limit, SDK error codes turned into translatable messages; `REVIEW_URL` and `for_review()` for languages with Translation review; User-Agent `djangoCMS-Supertext-Translation/<version>`. No Django imports; session and `sleep` injectable for tests |
| `_vendor/supertext/` | Bundled copy of the Supertext Python SDK (see *Supertext SDK*). Never edit |
| `_vendor/plugin_health/` | Bundled copy of Supertext Plugin Health (see *Supertext Plugin Health*). Never edit |
| `conf.py` | `SUPERTEXT` setting + `SUPERTEXT_API_KEY` / `SUPERTEXT_API_URL` / `SUPERTEXT_REVIEW_URL` / `SUPERTEXT_VERSION_REPORTS`; *Translation review* per language (`Options.review()`: `LANGUAGES` → `review`, else the settings page); language code → Supertext code (mapping: `LANGUAGES` override, else the settings page's `LanguageSetting` rows; else exact match, else the SDK default, else `unsupported_language`) and tone; `DEFAULT_PLUGIN_FIELDS` |
| `translator.py` | Field rules, translation, creating/replacing the target language (`collect()` and `apply()` are shared with the translation files) |
| `files.py` | *Export for translation* / *Import translation*: XLIFF and HTML with the SDK's `files` (see *Translation files*) |
| `models.py` | `Translation` (log; custom permission `translate`), `State` (key/value: the version reporter's JSON state), `LanguageSetting` (one row per django CMS language: `supertext_code`, `politeness`, `review`; migrations `0003_language_setting`, `0004_language_review`) |
| `admin.py` | Log list, translate dialog (with the export and import forms: `page/<id>/export/`, `page/<id>/import/`), settings page with the key check, *Test connection*, the reporting setting, the Languages table (a `<select>` per django CMS language from the SDK's `target_options()`, preselected with the saved value, else `suggest_target()`, else *— choose —*; `save_languages` validates against the SDK list and skips what `LANGUAGES` overrides; `LanguageSettingAdmin` shows the rows in the plain Django admin) and the plugin version (read from `djangocms_supertext.__version__`; X.Y.Z links to the GitHub release `vX.Y.Z`), and the public ping route (all as admin URLs, no URL include needed) |
| `reporting.py` | Commando Center: version reports and ping (Plugin Health's `InstallationReporter`), API key check (the SDK's `check_api_key`), site URL, ping path, state in `State`, the key-check messages |
| `views.py`, `urls.py` | The public ping view; `urls.py` is the optional include for `/supertext/ping` |
| `cms_toolbars.py` | The toolbar entry |
| `management/commands/` | `supertext_translate <page id> --from en [--to de-ch fr-ch] [--overwrite]`, `supertext_check` (key check, a `check` report, the plugin version) |
| `locale/{de,fr,it}/` | German, French and Italian strings (`django.po` and compiled `django.mo`) |

### Field rules

- **Page content** (`PAGE_FIELDS`): `title`, `page_title`, `menu_title`, `meta_description`, as plain text.
- **Slug**: a new language gets django CMS's default slug from the translated title (`create_page_content(slug=None)`), unique within its parent. Existing languages keep their slug.
- **New language settings** (`COPIED_PAGE_SETTINGS`): `template`, `in_navigation`, `soft_root`, `limit_visibility_in_menu`, `xframe_options` come from the source.
- **Plugins**: every plugin of the source's placeholders is copied (`copy_plugins_to_placeholder`, so nested plugins and `copy_relations` work). Fields listed in `PLUGIN_FIELDS` for the plugin type are translated (`"html"` as HTML, `"text"` escaped). Defaults: `TextPlugin.body` (html), `LinkPlugin.name`, `PicturePlugin.caption_text`, `FilePlugin.file_name`, `VideoPlayerPlugin.label`.
- **Inline plugins** in text bodies (`<cms-plugin id="…">`) are remapped to the copies' ids after copying; their own texts (e.g. a link's name) are translated as plugins.
- **Overwrite** replaces the target's page fields and deletes the target's top-level plugins in each placeholder that the source has, then copies the source's.
- Empty values are skipped; an empty translation never overwrites.

Each value is one `data-st-id` element, so a whole Text plugin (all its paragraphs, bold words and links) is translated in context.

**djangocms-versioning:** `create_page_content` creates the new language as a draft version. Existing languages are only changed if their latest version is a draft (`_check_editable`).

## Supertext API protocol

Shared with every Supertext plugin. Every call goes through the Supertext SDK (see *Supertext SDK*); this is what it does:

1. `POST {base}translate/ai/file`: multipart with `file` (part `Content-Type` exactly `text/html`, no charset, or the API answers 415), `target_lang` (BCP-47, e.g. `de-CH`), optional `source_lang` (primary subtag only, e.g. `en`, or the pair is rejected), optional `politeness` (`more`/`less`). Returns `{file_id}`.
2. `GET …/{file_id}/status` until `done` (`error`, `limit_exceeded`, `deleted` are terminal).
3. `GET …/{file_id}/translation` returns the translated HTML.
4. `DELETE …/{file_id}` (files also expire after 24 h).

Auth header: `Authorization: Supertext-Auth-Key <key>`. The header name must be `Authorization` (`Authentication` gets 403). Supertext shows the key with the prefix, so the client strips a pasted `Supertext-Auth-Key ` and always sends exactly one. Base URLs: `https://api.supertext.com/v1/` (live), `https://api.staging.supertext.com/v1/`, `https://api.testing.supertext.com/v1/`. `GET features` is the cost-free key check (*Test connection*, `supertext_check`).

**Rate limit:** the API limits requests per second per key (HTTP 429). The client retries a 429 up to 4 times, waiting for `Retry-After` if sent, otherwise 1, 2, 4 and 8 seconds plus jitter. Languages are translated one after the other.

**Translation review** (`LanguageSetting.review`, per target language, off by default; `SUPERTEXT["LANGUAGES"][code]["review"]` overrides it): `translator.translate_page` takes `client.for_review(options.review(target))` for each target, a second `SupertextClient` with the same key, timeouts, `requests` session, `sleep` and User-Agent whose base URL is `REVIEW_URL` (default `client.REVIEW_URL`, the translation proxy of [Supertext Localization Review](https://github.com/Supertext/Localization-Review-Supertext-Translation); `SUPERTEXT_REVIEW_URL` wins when set). It is created once per client. Each document goes through the SDK's `translate_html` round trip (upload, status, download, delete) on one client, so a job is always collected by the client that submitted it. The proxy speaks the same API v1, forwards to the live Supertext API with the plugin's key, stores every segment per key and serves reviewers' corrections on the next upload, so nothing else changes in the plugin. `REVIEW_URL: ""` (or the same URL as the API) means `for_review()` always returns the direct client. The key check (`reporting.py` builds its own client), the version reports and the translation files never use the review service. Tests: `test_client.py` (all four calls to the review URL, one review client, none without a separate URL, the default), `test_conf.py` (default, `""`, the environment variable, per-language override) and `test_translator.py` (a review language through the review service while the other goes directly, `""` turns it off, the checkbox on the settings page).

## Supertext SDK

The protocol above, the retries, the language list (`Languages`), the API key check (`check_api_key()`, `api_key_fingerprint()`), the translation files (`files`, SDK 0.5.0) and the `data-st-id` document (plain text escaped with `<br>` for line breaks, HTML as is) come from the official Supertext Python SDK ([Supertext/Supertext-API-SDK-and-Guide](https://github.com/Supertext/Supertext-API-SDK-and-Guide)). The package ships a copy in `djangocms_supertext/_vendor/supertext/` (imported as `djangocms_supertext._vendor.supertext`, so an installed `supertext-sdk` can never clash with it); sites install nothing extra. The API lives in its `v1` subpackage (`djangocms_supertext._vendor.supertext.v1`, SDK 0.2.0+); the SDK uses relative imports, so the copy needs no rewriting. `COMMIT` and `VERSION` there name the SDK revision; `client.SDK_VERSION` reads it. Since SDK 0.3.0 the SDK provides only the client and the key check: version reports and the ping come from Supertext Plugin Health (below).

- Never edit `_vendor/`. Fix the SDK in its repository, then run `scripts/vendor-sdk.sh [ref]` (default `main`; `SDK_DIR=/path/to/clone` uses a local clone; it copies the package with its subpackages) and the tests.
- `client.SupertextClient` keeps the package's interface (`translate_document`, `translate_segments`, `validate_api_key`) and turns every SDK error code into a `SupertextError` with a translatable template (`client.MESSAGES`). A new SDK error code needs a message there and in the three `.po` files.
- The live API answers an unknown language (`xx-YY`) with HTTP 404 `INVALID_LANGUAGE_PAIR`; the SDK reports it as `invalid_language_pair` with both codes, shown as "Supertext does not support this language pair (en → xx-YY)".

## Translation files (XLIFF and HTML)

*Export for translation* and *Import translation* use the SDK's `files` module (`djangocms_supertext._vendor.supertext.files`, SDK 0.5.0; integration guide → *Translation files*). The glue is `files.py`; the views are `TranslationAdmin.export_view` (POST `page/<id>/export/`, fields `export-source`, `export-targets`, `export-format`; answers with the file as an attachment) and `import_view` (POST `page/<id>/import/`, multipart `import-file`, `import-include_changed`, `import-overwrite`; renders the dialog with the summary). Both need `djangocms_supertext.translate` and permission to change the page; the import checks the permission again for the page each job names.

- Segments: `translator.collect()` (the units an API translation sends), keyed `page.<field>` (`page.title`, `page.menu_title`, …) and `plugin.<source plugin pk>.<field>` (`plugin.12.body`). The import collects them again, maps the keys back to unit indexes and writes through `translator.apply()`, the API translation's write-back (`_apply`: new language created, existing one only with *Overwrite existing translations*, drafts only with djangocms-versioning, the source's plugins copied, inline plugin ids remapped). Units without an imported text keep the source's text, as plugins are copies of the source's. A `Translation` log row with the message `XLIFF` or `HTML` records the import.
- Job metadata: `plugin` `djangoCMS-Supertext-Translation`; `reference` **`page:<page id>:<source language>:<target language>`** with django CMS language codes (`page:12:en:fr-ch`); `sourceLanguage`/`targetLanguage` from `Options.source_code()`/`target_code()` (the mapping), else the django CMS code with `-`, so unmapped languages don't block an export.
- File names `djangocms-page-<id>-<target code>.xlf`/`.html`, `djangocms-page-<id>.xlf` for several languages; `application/x-xliff+xml` / `text/html; charset=utf-8`.
- Uploads over 10 MB are refused before they are read (`files.check_size(upload.size)`); the content is decoded and parsed in memory. The SDK refuses DTDs and markup the current source doesn't have.
- The export and import forms stop the django CMS modal's own submit handler (`stopImmediatePropagation()` in `translate.html`): after the dialog's *Translate* button was used, the modal treats any submitted form as saved and hides the dialog.
- `source_changed` results are written only with *Also import texts whose source changed since the export*; `untranslated`, `invalid_markup` and `missing` never.

## Supertext Plugin Health

Version reports to the Supertext Commando Center, the API key check result and the reachability ping come from **Supertext Plugin Health**, a dependency-free library that lives next to the center ([Supertext/Commando-Center-Supertext-Translation](https://github.com/Supertext/Commando-Center-Supertext-Translation) → `plugin-health/python`). It doesn't talk to Supertext itself: `reporting.py` passes it the SDK's key check (`CallableKeyChecker(check=…check_api_key(), fingerprint=api_key_fingerprint)`) and `SDK_VERSION`. The package ships a copy in `djangocms_supertext/_vendor/plugin_health/` (imported as `djangocms_supertext._vendor.plugin_health`, so an installed `supertext-plugin-health` can never clash with it), next to the SDK's; it uses relative imports, so the copy needs no rewriting. `COMMIT` and `VERSION` there name its revision.

- Never edit `_vendor/plugin_health/`. Fix it in Commando-Center-Supertext-Translation/plugin-health, then run `scripts/vendor-plugin-health.sh <tag>` (e.g. `plugin-health-v0.1.0`; default `main`; `PLUGIN_HEALTH_DIR=/path/to/clone` uses a local clone of the center's repository) and the tests. The script fails if an absolute `supertext_plugin_health` import is left.
- Its state is the same camelCase JSON the SDK 0.1–0.2 reporter stored, so switching kept every site's history (no new `installed` report).

## Language codes

Supertext accepts exactly the codes its `GET features` lists (the SDK's `Languages`, from the live API): bare sources (`en`, `de`); targets in one exact form each, regional for German, English, French, Italian and Portuguese (`de-CH`, `en-US`, `pt-BR`), with a script for Chinese and Serbian (`zh-Hans`, `sr-Latn`), a dialect for Swiss German (`gsw-u-sd-chzh`), bare for the others (`es`, `nl`, `sl`). Anything else is HTTP 404 `INVALID_LANGUAGE_PAIR`; formal/informal for a target without it (`en-US`, `rm`, …) is HTTP 400 `FEATURE_ERROR` (`unsupported_feature`). The old default regions (`es-ES`, `sl-SI`, `zh-CN`) are rejected, so there are none.

`conf.py` turns django CMS language codes into Supertext codes with the SDK's `Languages.target()`/`source()` (**defaults only where obvious**):

- **Mapping** (`Options.mapping()`): the Supertext languages chosen on the settings page (`LanguageSetting` rows, read by `conf.saved_languages()` into `Options.saved`; `{}` before `migrate`), overridden per language by `SUPERTEXT["LANGUAGES"]` → `code` (`Options.languages`). `politeness` works the same way (`override_politeness`, else the saved value). `conf.load(options, saved=…)` lets tests pass both.
- **Target** (`Options.target_code`): the mapping (sent as it is), else a django CMS code that equals a Supertext code apart from case and `_`/`-` (`de-ch` → `de-CH`, `es`), else the SDK default (`Languages.default_target`: `de` → `de-DE`, `en` → `en-US`, `fr` → `fr-FR`, `it` → `it-IT`, `pt` → `pt-PT`, `zh`/`zh-cn` → `zh-Hans`, `zh-tw` → `zh-Hant`, `sr` → `sr-Latn`, `es-es` → `es`), else `SupertextError` `unsupported_language` with `%(language)s` (`en-ie`, `de-li`, `gsw`, `sr-rs`). `translator.translate_page` reports it for that language and sends nothing for it; the message names the settings page.
- **Source** (`Options.source_code`): the SDK's `Languages.source()` with the same mapping, which sends a mapped value in its source form (`de` chosen as `de-CH` translates from `de`; one mapping for both directions), else the code's language (`en-us` → `en`), else `unsupported_language`.
- **Politeness**: `client.translate_document` refuses `more`/`less` for a target whose `Languages.supports_politeness()` is `False` before sending (`unsupported_feature`), so the admin's setting is never silently dropped. The settings page only offers the form of address where the chosen target supports it (a small script toggles it when the select changes) and `save_languages` stores `default` otherwise; it still warns about an unsupported tone set under `LANGUAGES`.
- **The settings page** (`admin._language_row`): the select's value is the override, else the saved code, else `Languages.suggest_target()` (marked *Suggested*: that is what a translation uses until someone saves another one), else *— choose —* with the row marked (only languages without mapping **and** without default). Option labels are "Name (code)", the name from Django's `get_language_info()` in the admin's language where Django knows the code or its language, else the SDK's English name.

`tests/fake.py` and `tests/docs/stand-in.mjs` accept exactly the SDK's target list (404 for anything else) and reject politeness where it isn't offered, like the live API.

## Commando Center: version reports, key check, ping

Protocol: [Commando-Center-Supertext-Translation](https://github.com/Supertext/Commando-Center-Supertext-Translation) → `docs/DEVELOPER.md` → *Report protocol*; Plugin Health's `InstallationReporter`, `reports_enabled()`, `ping_response()` and `reporter_state()` implement it with the SDK's `check_api_key()` as the key check, `reporting.py` only supplies what django CMS knows:

- **Setting:** `SUPERTEXT["VERSION_REPORTS"]` (default on), `SUPERTEXT_VERSION_REPORTS` wins (`reports_enabled(setting)`). Off: no reports, ping 404. `SUPERTEXT_REPORT_URL` sends reports elsewhere (tests, the stand-in).
- **Report fields:** `site_url` = `SUPERTEXT["SITE_URL"]`, else the admin request's scheme and host, else (commands) `https://<Django site domain>` unless it is still `example.com` (then nothing is reported, the key is still checked); plugin `djangoCMS-Supertext-Translation` with `djangocms_supertext.__version__`; system `django CMS` with `cms.__version__`; runtime Python (Plugin Health default); `sdk_version` = the bundled SDK's `SDK_VERSION`; `callback.url` = site URL + `reverse("djangocms_supertext_ping")` if the site includes `djangocms_supertext.urls`, else `reverse("admin:djangocms_supertext_ping")` (in `LANGUAGE_CODE`, so it doesn't change with the admin language). Reports and the key check go through the plugin's `RequestsTransport` (proxies; reports through a small adapter from Plugin Health's request type).
- **When:** the settings live in Django's settings file, so there is no `settings_saved`. `on_request` runs after the response has been sent (appended to the response's `_resource_closers`, which Django calls when the server closes the response) on the settings page and the translate dialog, and synchronously after `supertext_translate`: it reports `installed`, `upgraded` or `api_key_check` and checks the key only when its fingerprint changed. *Test connection* (POST to the settings page) runs `test_connection` and shows its result. A translation with `authentication_failure` runs `authentication_failed` (the result's `http_status`). `supertext_check` runs `test_connection`, then `report_check`. Front-end page views never report. Nothing in `reporting.run()` ever raises.
- **State:** `State(key="reporter")`, Plugin Health's camelCase JSON (the same the SDK 0.1–0.2 reporter stored) (`reportedVersions`, `reportedKeyStatus`, `lastFailureAt`, `keyCheck` with the key fingerprint, never the key), migration `0002_state`.
- **Messages:** `reporting.check_message()` has the center's key-check texts (`.po` files); `check_html()` links *supertext.com* and *supertext.com → Integrations → API* (new tab) for `invalid`/`missing`.
- **Ping:** `views.ping`, GET only, no login (deliberately not wrapped in `admin_view`), CSRF-exempt, Plugin Health's status, headers (`Cache-Control: no-store`) and body.

## Local development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]" -r demo/requirements.txt
cd demo
python manage.py migrate
DEMO_ADMIN_EMAIL=you@example.com DEMO_ADMIN_PASSWORD='choose-one-1' python manage.py demo_setup
SUPERTEXT_API_KEY=… DJANGO_DEBUG=1 python manage.py runserver
# site: http://localhost:8000/en/   admin: http://localhost:8000/en/admin/
```

Without `DATABASE_URL` the demo uses SQLite (`demo/db.sqlite3`). To work without a real key, run the stand-in API (`node tests/docs/stand-in.mjs`) and start Django with `SUPERTEXT_API_KEY=anything SUPERTEXT_API_URL=http://127.0.0.1:8765/v1/ SUPERTEXT_REPORT_URL=http://127.0.0.1:8765/report` (the last one keeps version reports away from the live Commando Center). It returns real German, French and Italian for the demo's pages and `[de-CH] …`-prefixed text for anything else.

## Tests

```bash
pytest
```

- `tests/test_client.py`: the SDK wrapper: protocol, auth header and prefix, User-Agent with the version, 429 retries, errors (language pair included), clean-up, segments in one document, the review service client (`for_review`: all four calls to the review URL, created once, none without a separate URL, `REVIEW_URL` is Supertext's review service). `tests/fake.py` reads the SDK's multipart body back.
- `tests/test_conf.py`: settings, language codes (exact codes, the SDK defaults, no guessing beyond them, the `LANGUAGES` mapping, the settings page's mapping and its override, sources), `REVIEW_URL` (default, `""`, `SUPERTEXT_REVIEW_URL`), *Translation review* per language (off by default, override wins) and the reporting setting.
- `tests/test_translator.py`: end to end on SQLite with a fake API: a page with Text plugins in two placeholders is translated into two languages (fields, slug, markup, tone, plugins in the right placeholders, source untouched), skip and overwrite (no duplicated plugins), per-language errors (a language without mapping or default and an unsupported tone send nothing), a Supertext language chosen on the settings page, *Translation review* (a review language goes through the review service, all four calls, while the other goes directly; an empty `REVIEW_URL` turns it off; the checkbox saved on the settings page), the translate dialog as an editor (and 403 without the permission), the settings page (including the plugin version and its release link) and *Test connection*.
- `tests/test_files.py`: XLIFF/HTML export and import end to end: reference round trip, the mapping and the fallback for unmapped codes, the collector's keys, HTML with one language only, nothing to export, `ok` written through the API write-back (fields, plugins, markup, log row), an existing language only with overwrite, `source_changed` only with the option, `untranslated`/`invalid_markup`/`missing` not written, errors per job (other system, unknown reference, deleted page, missing language, no permission), invalid files and the 10 MB limit, the dialog's export download and import summary, 403 without the permission.
- `tests/test_reporting.py`: the Commando Center with the fake (`tests/fake.py` answers `REPORT_URL` with 202): one `installed` report from the settings page (fields, `sdk_version`, callback URL, never the key), state stored by the SDK 0.1–0.2 reporter kept (no new report), the bundled versions, nothing when nothing changed, `upgraded`, reports off (setting and environment; ping 404, key still checked), ping answers (200/400/405), *Test connection* with a rejected key (links, `api_key_check`), a 401 during translation reported once, `supertext_check`'s `check` report, no site URL, center and database failures, the messages in four languages, the Languages table (preselection: override, saved, suggestion, *— choose —*; saving, validation, override kept; option names in the admin's language) and the tone warning.
- `tests/conftest.py`: every test runs against a `FakeSession` with `SUPERTEXT_REPORT_URL` pointing at the fake, so no test reaches the live API or the live center.
- `tests/test_versioning.py` (`pytest --ds=tests.settings_versioning tests/test_versioning.py`, needs djangocms-versioning): new languages are drafts, published languages are not overwritten.

CI (`.github/workflows/ci.yml`) on every push and pull request:

- **test**: the suite on Python 3.11 with django CMS 4.x and Django 4.2, 3.12 with django CMS 5.0 and Django 5.2, 3.13 with django CMS 5.1 and Django 6 (plus the versioning test), and 3.14 with django CMS 5.1 and Django 6.
- **demo**: builds the demo image, starts it twice against PostgreSQL with the stand-in (`tests/demo-check.sh`): demo accounts created once and never duplicated, no passwords in the log, the editor's permissions, `supertext_check`, the public ping and the `installed` and `check` reports the stand-in received (`GET /reports`; never the key), translation of the sample page into three languages, the skip on a second run, and the German and French pages with their translated slugs and markup.

## Demo (Railway)

The public demo is a container built from `demo/Dockerfile`: django CMS 5.1 with djangocms-text and this package, English plus German, French and Italian (Switzerland), a home page and a sample article. It runs on Railway in the `supertext-cms-demos` project, service `djangoCMS`, region EU West (Amsterdam): <https://djangocms-production.up.railway.app/en/> (admin: `/en/admin/`). The data lives in a `djangocms` database on the project's PostgreSQL service.

**Deploys:** Railway builds `main` of this repository (`railway.json` points it at `demo/Dockerfile`).

**What's in `demo/`:**

| File | Purpose |
| --- | --- |
| `Dockerfile` | `python:3.13-slim`, the demo's requirements and this package (installed from the repository), `collectstatic` |
| `entrypoint.sh` | Every start: creates the database if missing, `migrate`, `demo_setup`, then gunicorn on `$PORT` |
| `demo/settings.py` | Settings from environment variables; PostgreSQL via `DATABASE_URL` (database name `DJANGOCMS_DB_NAME`); WhiteNoise; `CMS_PERMISSION = False`; Supertext with `SITE_URL` from `RAILWAY_PUBLIC_DOMAIN` |
| `site_setup/` | The page template (`page.html` with a language chooser) and the `demo_setup` command (also chooses `de-CH`, `fr-CH`, `it-CH` with the formal tone on the settings page for languages nobody has chosen yet; `en` uses the default `en-US`) |
| `createdb.py` | Creates the demo database on the server from `DATABASE_URL` |
| `.env.example` | The variables below |

**No volume:** Railway's volume limit for the project is reached, and the demo needs none: everything is in PostgreSQL. Uploaded media would disappear with the next deploy.

**Service variables:**

| Variable | |
| --- | --- |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}`; the demo database (`DJANGOCMS_DB_NAME`, default `djangocms`) is created on that server if missing |
| `DJANGO_SECRET_KEY` | Random secret |
| `DEMO_ADMIN_EMAIL`, `DEMO_ADMIN_PASSWORD` | Superuser (the e-mail address is also the username) |
| `DEMO_EDITOR_EMAIL`, `DEMO_EDITOR_PASSWORD` | Editor for automated tests and screenshots: staff user in the **Editors** group (pages, page contents, text plugins, *Can translate pages with Supertext*). django CMS has no built-in editor role, so `demo_setup` creates this group. |
| `SUPERTEXT_API_KEY` | Supertext key |
| `SUPERTEXT_API_URL` | Optional, e.g. a stand-in API (to try the review service, tick *Translation review* on the settings page instead) |
| `SUPERTEXT_REVIEW_URL` | Optional: another review service than Supertext's (`REVIEW_URL`; empty keeps the default) |
| `SUPERTEXT_VERSION_REPORTS` | Optional; `0` turns the version reports off (default on; the demo reports with `SITE_URL` = `https://$RAILWAY_PUBLIC_DOMAIN`) |
| `SUPERTEXT_REPORT_URL` | Tests only: where reports go instead of the Commando Center (e.g. the stand-in's `/report`) |
| `PORT` | Port gunicorn listens on (Railway sets it) |

Railway also sets `RAILWAY_PUBLIC_DOMAIN`, which the settings use for `CSRF_TRUSTED_ORIGINS` and `demo_setup` for the Django site's domain.

**Demo accounts:** on every start `demo_setup` creates the `DEMO_ADMIN` and `DEMO_EDITOR` accounts if no account with that e-mail address or username exists. Existing accounts are never changed; change passwords in the admin. Passwords must pass Django's password validators (at least 8 characters, not too common, not only digits, not too similar to the e-mail address); if one doesn't, that account is skipped with a warning naming the variable and the rule, and the demo still starts. django CMS has no first-run "create admin" screen; without `DEMO_ADMIN_*` there is simply no superuser.

**Run it locally:**

```bash
docker build -f demo/Dockerfile -t supertext-djangocms-demo .
docker run --rm -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:pass@host.docker.internal:5432/postgres -e DJANGO_SECRET_KEY=dev \
  -e DEMO_ADMIN_EMAIL=you@example.com -e DEMO_ADMIN_PASSWORD='choose-one-1' \
  -e SUPERTEXT_API_KEY=… supertext-djangocms-demo
```

## Docs screenshots

The images in `docs/images/` are generated by `tests/docs/screenshots.mjs` (Playwright) from a freshly set-up demo whose package talks to `tests/docs/stand-in.mjs`. The stand-in returns German, French and Italian for the demo's pages (`samples.json`, real Supertext output) and answers `POST /report` with 202, so screenshots never report to the live center (start Django with `SUPERTEXT_REPORT_URL=http://127.0.0.1:8765/report`). It also exports the sample page as HTML into Italian, fills in the Italian from `samples.json` and imports the file (`09-export.png`, `10-import-summary.png`). Regenerate them whenever a screen they show changes:

```bash
cd tests/docs && npm install && npx playwright install chromium
npm run stand-in &
# a fresh demo database (migrate + demo_setup with DEMO_* set), served on :8095 with
# SUPERTEXT_API_KEY=anything SUPERTEXT_API_URL=http://127.0.0.1:8765/v1/ SUPERTEXT_REPORT_URL=http://127.0.0.1:8765/report
BASE_URL=http://127.0.0.1:8095 DEMO_ADMIN_EMAIL=… DEMO_ADMIN_PASSWORD=… \
  DEMO_EDITOR_EMAIL=… DEMO_EDITOR_PASSWORD=… npm run screenshots
```

On the settings page the script shows the live API address and the public demo's domain (`SITE_DOMAIN`, also in the ping address) instead of the local ones. The stand-in's port can be changed with `PORT=…` (then adjust the URLs above).

## Demo movie

`docs/images/demo.gif` (at the top of the README) is recorded by `tests/docs/movie.mjs` with Supertext's shared movie kit (`tests/docs/movie/movie-kit.mjs` and `assets/`: intro and outro cards, caption bar, cursor, cuts the waiting time; Inter under the SIL OFL, `assets/fonts/Inter-LICENSE.txt`). It shows, with a spoken line for every step (the GIF is silent), as the demo's editor: the sample page in English in edit mode, the toolbar's *Language → Translate with Supertext…*, *Translate* for German, French and Italian (all ticked), the waiting state, the results and the German page via *Open*. Run it against a fresh demo (the page must have no translations yet) and the stand-in with a delay, so the waiting state is visible:

```bash
cd tests/docs && npm install && npx playwright install chromium
pip install piper-tts                     # the voice (optional, see below)
STAND_IN_DELAY=3 npm run stand-in &
# a fresh demo as for the screenshots, served on :8095
BASE_URL=http://127.0.0.1:8095 DEMO_EDITOR_EMAIL=… DEMO_EDITOR_PASSWORD=… npm run movie
```

`STAND_IN_DELAY=<seconds>` keeps the stand-in's files `in_progress` that long. The MP4 is narrated with [Piper](https://pypi.org/project/piper-tts/) (`pip install piper-tts`): the kit's `say()` speaks each step's line, shows its caption and holds until the line is finished; the time spent making the speech is cut. The voice model (63 MB, pinned revision, checked by SHA-256) downloads itself once into `tests/docs/movie/voice/` (git-ignored; never commit it). Without Piper, or with `MOVIE_VOICE=0`, the movie is made silent with the captions only.

Voice: Piper voice “alba” (en_GB), trained on a dataset from the University of Edinburgh's Centre for Speech Technology Research, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)

It needs `ffmpeg` and writes 1280×720 at 30 fps. The GIF (800 px, 12 fps, keep it under 3 MB) is committed; the MP4 isn't: it goes to `tests/docs/movie/out/djangoCMS-Supertext-Translation.mp4` (git-ignored) or to `MOVIE_OUT`. `CHROMIUM_PATH` picks a Chromium other than Playwright's. Record it again when the translate dialog or the toolbar entry changes. The kit is the same in every Supertext plugin repo: don't restyle it here.

### Install movie

`tests/docs/movie-install.mjs` records the install and configuration movie with the same kit and voice (MP4 only, no GIF). It shows the steps from `docs/INSTALLATION.md` in the kit's terminal (`pip install` from GitHub, `INSTALLED_APPS` and `LANGUAGES` in the settings, `migrate djangocms_supertext`, `SUPERTEXT_API_KEY` with the fake key `st-demo-0000-0000-0000` and `supertext_check`), then, as the demo's **administrator**: *Supertext translations → Settings and connection* (key set, where to get a key, *Test connection*), the Languages table (German → *German (Switzerland) (de-CH)*, *Translation review* left off, *Save languages*) and, for editors, the toolbar's *Language → Translate with Supertext…*. Page loads are cut, and the local addresses are shown as `https://api.supertext.com/v1/` and the public demo's domain (`SITE_DOMAIN`). Run it against the same demo and stand-in:

```bash
BASE_URL=http://127.0.0.1:8095 DEMO_ADMIN_EMAIL=… DEMO_ADMIN_PASSWORD=… npm run movie:install
```

The MP4 (about 90 s) goes to `tests/docs/movie/out/djangoCMS-Supertext-Translation-install.mp4` (git-ignored) or to `MOVIE_OUT`; it isn't committed. Record it again when the install steps or the settings page change.

## Code quality and security checks

- **Checks** workflow (`.github/workflows/checks.yml`): [actionlint](https://github.com/rhysd/actionlint) and [zizmor](https://docs.zizmor.sh/) lint the workflows on every push and pull request. Dependency review fails a pull request that adds a package with a known vulnerability (moderate or worse). Actions are pinned to commit SHAs; Dependabot keeps the pins up to date. To run the workflow lint locally: `pip install actionlint-py zizmor`, then `actionlint` and `zizmor .github/workflows` in the repo root.
- **Links** workflow (`.github/workflows/links.yml`): [lychee](https://lychee.cli.rs/) checks the links in all Markdown files weekly and whenever docs change on `main`. Broken links open (or update) the issue "Broken links in the docs". Links that can't work from CI (local URLs, placeholders, pages behind a login) are excluded in `.lycheeignore`.
- Python and the demo's JavaScript are analysed by CodeQL (see below), so this repo runs no separate static analyser.
- GitHub settings (set by Remy's setup script, not stored in the repo): **secret scanning with push protection** (a push containing a known token format is rejected; findings under *Security → Secret scanning*) and **CodeQL default setup** (findings under *Security → Code scanning* and as comments on pull requests; PHP isn't covered by CodeQL, which is why the PHP plugins run PHPStan).
- `.github/workflows/support-triage.yml`: support requests from the Supertext integrations website arrive as issues labelled `support` (contact details stay in the Supertext CMS). Claude classifies each one: answers questions (marked `<!-- supertext:reply -->`, emailed to the sender by the CMS) and closes them, fixes bugs as pull requests for review (never merged automatically), labels feature requests `feature-request`. Only people with triage rights can add labels, so outsiders can't start it. Needs the organisation secret `ANTHROPIC_API_KEY`; the workflow is the same in every Supertext repo.

Before starting work in this repo, look at its open findings: code scanning alerts, secret scanning alerts, Dependabot PRs and the "Broken links in the docs" issue.

## Dependency updates

Dependabot (`.github/dependabot.yml`) opens weekly pull requests: minor and patch updates grouped into one, GitHub Actions in another, each major update on its own.

`.github/workflows/dependabot-merge.yml` merges a minor or patch package update by itself once every other check on its pull request has passed (it waits up to 85 minutes and leaves the pull request alone if a check fails). GitHub Actions updates and majors stay for a person: the workflow's built-in token can't merge changes to workflow files, and a major needs a decision. Merges by the workflow don't start CI on `main`; the weekly health check looks at `main`.

## Releasing

Releases are published by `.github/workflows/release.yml` when the version is officially bumped; nobody tags or creates releases by hand.

1. Check that if messages changed, each `.mo` is recompiled (`python -c "import polib; polib.pofile('djangocms_supertext/locale/de/LC_MESSAGES/django.po').save_as_mofile('djangocms_supertext/locale/de/LC_MESSAGES/django.mo')"`, same for `fr` and `it`; `tests/test_locale.py` fails otherwise).
2. Move the *Unreleased* entries in `CHANGELOG.md` under a new `## X.Y.Z — YYYY-MM-DD` section, and keep an empty *Unreleased* above it.
3. Set the same version in:
   - `djangocms_supertext/__init__.py`: `__version__`, the Python package version
4. Push to `main`. The workflow checks that the version files match `CHANGELOG.md`, then tags `vX.Y.Z` and creates the GitHub release with the CHANGELOG section as notes (0.x versions as pre-releases). A push that adds no new version does nothing, and a version that is already released is skipped. After fixing a failed run, start it again with *Run workflow* on the *Release* workflow.

Publishing to PyPI (`python -m build && twine upload dist/*`) is planned.
## Conventions

- Black-compatible formatting, type hints in new code.
- User-visible strings via Django's gettext, translated in `djangocms_supertext/locale/{de,fr,it}/LC_MESSAGES/django.po` (English is the source). New or changed strings need all four languages in the same commit. `client.py` has no Django imports, so it marks its error messages with a local `gettext_noop` and keeps `template`/`params` on `SupertextError`; `translator.localized()` translates them for the dialog, the settings page and the log. `tests/test_locale.py` checks that every marked string is in each catalog, placeholders match and the `.mo` files are current.
- Keep `client.py` free of Django imports.
- Keep the three docs in `docs/` current with every change (see `CLAUDE.md`).

## Known limitations / roadmap

- Translation runs inside the editor's request (one language after the other, up to `TIMEOUT` each). Planned: background translation and translating a page tree in one go.
- Overwriting replaces all plugins of the target language with translated copies of the source's; plugins that exist only in the target language are removed in placeholders the source has.
- Existing languages keep their slug when overwritten.
- Static placeholders/aliases (djangocms-alias) and apphook content are not translated.
- With djangocms-versioning, only drafts can be overwritten.
- Re-translating (overwrite) replaces manual changes in the translated texts; no change detection. A translation memory and reviewers' corrections come from the review service when a language has *Translation review* on; corrections reach django CMS only with the next translation (no push).
- Settings other than the Languages table (Supertext language, form of address, *Translation review*) live in Django's settings file, and version reports have no `settings_saved` event (the key check runs on a changed key instead).
- *Export for translation* exports one page at a time (XLIFF can hold several languages); a bulk export of a page tree into one XLIFF file would be the next step.
- Not on PyPI yet.
- Human (professional) translation orders are not supported yet (the WordPress plugin has them).
