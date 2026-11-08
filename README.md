# Supertext Translation for django CMS

Translate django CMS pages into the site's other languages with **Supertext AI**, right from the toolbar.

![Demo: an English page in django CMS, the toolbar's Language menu → Translate with Supertext…, Translate in the dialog for German, French and Italian, and the German version of the page](docs/images/demo.gif)

In edit mode, choose **Language → Translate with Supertext…**, tick the languages and click **Translate**: the page's title, menu title, meta description and the texts of its plugins go to Supertext in one request per language and come back as a new language version of the page, with all plugins in place. Editors review and adjust it like any other page content.

- Uses django CMS's own languages and page contents; works with djangocms-versioning (new languages are drafts)
- Text plugins keep their headings, bold text, links and lists; whole paragraphs are translated in context
- Translated URL slugs for new languages
- Languages that exist are kept unless the editor explicitly overwrites them
- Text, Link, Picture, File and Video plugins out of the box; more plugin fields by setting
- Formal or informal tone and custom Supertext language codes per language
- **Export for translation** (XLIFF 1.2 or HTML) for translation tools, translators or Supertext's web app, and **import of the translated file**
- A settings page with an automatic API key check and *Test connection*, a translation log, management commands

![The Translate with Supertext dialog in the django CMS toolbar](docs/images/02-translate-dialog.png)

## Export for translation and import (XLIFF and HTML)

Besides translating with Supertext AI, you can export a page with its plugins as a file, have it translated elsewhere and import the result.

- **Where:** the export and import sections of the *Translate with Supertext* dialog (toolbar → Language).
- **Formats:** XLIFF 1.2 for translation tools such as Trados, memoQ or Phrase (formatting travels as protected tags; several target languages in one file), or HTML (one language per file) for translators or Supertext's web app, which keeps the file's head and `data-st-id` attributes, so the translated file imports as it is.
- **Import:** the file says what it was exported from and for which language. The translations are written with the same rules as a Supertext AI translation, and a summary shows what was imported and what was skipped: source changed since the export (import those anyway with *Also import texts whose source changed since the export*), not translated, formatting changed, not in the file.
- **Safe:** files over 10 MB, files from another system and translations that add markup the source doesn't have are refused; uploaded files aren't stored.

![Export for translation: file format (XLIFF 1.2 or HTML) and target languages](docs/images/09-export.png)

![The import summary: imported texts and the ones skipped and why](docs/images/10-import-summary.png)

Details: [user guide](docs/USER_GUIDE.md#export-for-translation-and-import-translated-files).

## Documentation

| Guide | For |
| --- | --- |
| [Installation guide](docs/INSTALLATION.md) | Administrators and developers: requirements, install, API key, languages, permissions, settings, troubleshooting |
| [User guide](docs/USER_GUIDE.md) | Editors: translating, reviewing, overwriting, what gets translated |
| [Developer guide](docs/DEVELOPER.md) | Architecture, API protocol, local development, tests, demo deployment, releases |

Requires a Supertext account ([create one or log in](https://www.supertext.com/person/en/account/signin)) and an API key from [supertext.com → Integrations → API](https://www.supertext.com/en/integrations/api) (Admin role in the Supertext account).

Quick start:

```bash
pip install git+https://github.com/Supertext/djangoCMS-Supertext-Translation.git
```

```python
# settings.py
INSTALLED_APPS += ["djangocms_supertext"]
# environment: SUPERTEXT_API_KEY="…"
```

```bash
python manage.py migrate djangocms_supertext
```

## Demo

`demo/` is a django CMS 5 site with English sample pages and German, French and Italian (Switzerland), deployed to Railway from this repository. See the [developer guide](docs/DEVELOPER.md#demo-railway).

Part of Supertext's translation plugins for open source CMSs, alongside [Wagtail](https://github.com/Supertext/Wagtail-Supertext-Translation), [WordPress](https://github.com/supertext/wordpress-polylang), [Drupal](https://www.drupal.org/project/tmgmt_supertext_ai) and others.

## Changelog and roadmap

See [CHANGELOG.md](CHANGELOG.md) and the [roadmap](docs/DEVELOPER.md#known-limitations--roadmap).

<!-- supertext-plugins:start (shared list, keep identical in every Supertext plugin repo) -->
## Supertext plugins for other systems

Supertext offers AI and professional translation plugins for these systems:

### Content management systems (CMS)

| System | Plugin | Type of integration | What it does |
| --- | --- | --- | --- |
| Adobe Experience Manager | [supertext-aem-connector](https://github.com/Supertext/supertext-aem-connector) | Translation connector: two AEM content packages for AEM's Translation Integration Framework. | Sends AEM translation projects to Supertext and imports the results |
| ApostropheCMS | [Apostrophe-Supertext-Translation](https://github.com/Supertext/Apostrophe-Supertext-Translation) | Apostrophe module (npm): a translation provider for Apostrophe's own *Localize…* step. | Translates pages and pieces as editors localize them, widgets and rich text included |
| Contao | [Contao-Supertext-Translation](https://github.com/Supertext/Contao-Supertext-Translation) | Contao bundle (Composer) that adds a back-end action. | *Translate with Supertext* in the site structure: pages or whole websites into other languages |
| Craft CMS | [CraftCms-Supertext-Translation](https://github.com/Supertext/CraftCms-Supertext-Translation) | Craft plugin (Composer) with a panel on the entry page. | Translates entries into your other sites, Matrix and rich text included |
| Directus | [Directus-Supertext-Translation](https://github.com/Supertext/Directus-Supertext-Translation) | Directus extension bundle (npm): interface, endpoint, Flow operation and module. | *Translate with Supertext* box on the item form, fills the Translations field |
| django CMS | [djangoCMS-Supertext-Translation](https://github.com/Supertext/djangoCMS-Supertext-Translation) | Django app (Python package) that adds a toolbar entry. | Translates pages and their plugins from the toolbar |
| Drupal | [tmgmt_supertext_ai](https://www.drupal.org/project/tmgmt_supertext_ai) | Drupal module: a translator provider for the Translation Management Tool (TMGMT), by MD Systems. | Translates TMGMT jobs with Supertext AI |
| Ghost | [Ghost-Supertext-Translation](https://github.com/Supertext/Ghost-Supertext-Translation) | Separate connector service (Ghost has no admin plugins): works through internal tags, webhooks and the Admin API. | Tag a post `#translate-…` and a translated draft appears |
| Grav | [Grav-Supertext-Translation](https://github.com/Supertext/Grav-Supertext-Translation) | Grav 2 plugin with an Admin2 panel. | Supertext panel in the page editor, Markdown kept intact |
| HubSpot | [HubSpot-Supertext-Translation](https://github.com/Supertext/HubSpot-Supertext-Translation) | Hosted app connected to HubSpot with OAuth, working through HubSpot's multi-language content. | Translates website and landing pages, blog posts, marketing emails and knowledge base articles into draft language versions |
| Joomla | [Joomla-Supertext-Translation](https://github.com/Supertext/Joomla-Supertext-Translation) | Joomla system plugin (installable package). | Translates articles into linked, unpublished language versions |
| Magnolia | [Magnolia-Supertext-Translation](https://github.com/Supertext/Magnolia-Supertext-Translation) | Magnolia module with a *Translate with Supertext* action in the Pages app. | Translates pages, areas and components into the site's other languages |
| Neos | [Neos-Supertext-Translation](https://github.com/Supertext/Neos-Supertext-Translation) | Neos package (Composer) that hooks into the content repository, with a Supertext backend module for translation files. | Translates automatically when an editor creates a page in another language |
| Orchard Core | [OrchardCore-Supertext-Translation](https://github.com/Supertext/OrchardCore-Supertext-Translation) | Orchard Core module (.NET) with an admin page and a localization hook. | Translates content items into other cultures, on demand or on localization |
| Payload CMS | [Payload-Supertext-Translation](https://github.com/Supertext/Payload-Supertext-Translation) | Payload plugin (npm) added to `payload.config`. | *Translate* button for localized collections and globals |
| Silverstripe | [Silverstripe-Supertext-Translation](https://github.com/Supertext/Silverstripe-Supertext-Translation) | Silverstripe module (Composer) on top of Fluent. | Supertext tab translates pages and Elemental blocks into Fluent locales |
| Strapi | [Strapi-Supertext-Translation](https://github.com/Supertext/Strapi-Supertext-Translation) | Strapi 5 plugin (npm) with a Content Manager panel. | Translates entries into other locales from the Content Manager |
| TYPO3 | [Typo3-Supertext-Translation](https://github.com/Supertext/Typo3-Supertext-Translation) | TYPO3 extension (Composer) that hooks into TYPO3's own localization, with a Supertext backend module for translation files. | Translates pages and content elements as editors localize them |
| Umbraco | [Umbraco-Supertext-Translation](https://github.com/Supertext/Umbraco-Supertext-Translation) | Umbraco package (NuGet) with a backoffice extension. | *Translate with Supertext* for pages, block lists and grids included |
| Wagtail | [Wagtail-Supertext-Translation](https://github.com/Supertext/Wagtail-Supertext-Translation) | Python package: a machine translator for wagtail-localize. | Translates pages and snippets inside wagtail-localize's editor |
| WordPress (Polylang) | [wordpress-polylang](https://github.com/supertext/wordpress-polylang) | WordPress plugin: a machine-translation service for Polylang Pro, plus professional translation orders. | AI translation next to DeepL in Polylang, and human translation orders |

### Product information management (PIM)

| System | Plugin | Type of integration | What it does |
| --- | --- | --- | --- |
| Akeneo PIM | [Akeneo-Supertext-Translation](https://github.com/Supertext/Akeneo-Supertext-Translation) | Akeneo PIM bundle with a *Translate with Supertext* action on the product page. | Translates products and product models into your other locales |
| AtroPIM | [AtroPIM-Supertext-Translation](https://github.com/Supertext/AtroPIM-Supertext-Translation) | AtroCore module with a button on the product and a mass action in the list. | Translates products and other AtroCore records into your other languages |
| Pimcore | [Pimcore-Supertext-Translation](https://github.com/Supertext/Pimcore-Supertext-Translation) | Pimcore bundle (Composer) with a *Translate with Supertext* button in Pimcore Studio. | Translates documents into linked language versions and data objects' localized fields |

### E-commerce

| System | Plugin | Type of integration | What it does |
| --- | --- | --- | --- |
| Magento | [Magento-Supertext-Translation](https://github.com/Supertext/Magento-Supertext-Translation) | Magento 2 module (also Mage-OS) with a mass action in the admin lists and a button on the edit pages. | Translates products, categories, CMS pages and blocks into your store views' languages |
| PrestaShop | [PrestaShop-Supertext-Translation](https://github.com/Supertext/PrestaShop-Supertext-Translation) | PrestaShop module with a bulk action in the back-office lists. | Translates products, categories and CMS pages into your shop's other languages |
| Shopify | [Shopify-Supertext-Translation](https://github.com/Supertext/Shopify-Supertext-Translation) | Shopify app in the Shopify admin. | Translates products, collections, pages and blog posts into all your shop's languages |
| Wix | [Wix-Supertext-Translation](https://github.com/Supertext/Wix-Supertext-Translation) | Wix app with a dashboard page (hosted service), working through Wix Multilingual. | *In development:* translates Wix Stores products and other Wix Multilingual content into your site's languages |

### Email marketing

| System | Plugin | Type of integration | What it does |
| --- | --- | --- | --- |
| Mailchimp | [Mailchimp-Supertext-Translation](https://github.com/Supertext/Mailchimp-Supertext-Translation) | Hosted app connected to Mailchimp with OAuth: Supertext folders in Mailchimp and a translate page. | *In development:* turns a campaign into one draft per language, each sent to the subscribers with that language |

### Design files (XLIFF round trip)

| Application | Plugin | Type of integration | What it does |
| --- | --- | --- | --- |
| Adobe InDesign | [Adobe-InDesign-Translation](https://github.com/Supertext/Adobe-InDesign-Translation) | InDesign scripts (ExtendScript). | Exports all text to XLIFF 1.2 for any CAT tool and imports the translations with formatting intact |
| Adobe Illustrator | [Adobe-Illustrator-Translation](https://github.com/Supertext/Adobe-Illustrator-Translation) | Illustrator scripts (ExtendScript). | Exports all text to XLIFF 1.2 for any CAT tool and imports the translations with formatting intact |
| CorelDRAW | [CorelDRAW-Supertext-Translation](https://github.com/Supertext/CorelDRAW-Supertext-Translation) | CorelDRAW VBA macro. | Exports all text to XLIFF 1.2 for any CAT tool and imports the translations with formatting intact |
<!-- supertext-plugins:end -->

## Support

Questions, problems or ideas? Use the [Supertext support form](https://integrations.supertext.com/en/support?platform=django-cms): describe what happened and you get an answer by email, in your language. Requests are tracked as issues in this repository, without your name and email address. Developers are welcome to open issues and pull requests here directly. Security issues: see [SECURITY.md](SECURITY.md).

## License

MIT. © Supertext AG
