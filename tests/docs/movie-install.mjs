#!/usr/bin/env node
/**
 * Records the install and configuration movie (a narrated MP4 that isn't committed) with the shared
 * Supertext movie kit (movie/movie-kit.mjs): the install steps from docs/INSTALLATION.md in a terminal
 * (pip install, INSTALLED_APPS and LANGUAGES, migrate, SUPERTEXT_API_KEY, supertext_check), then, as the
 * demo's administrator: Supertext → Supertext translations → Settings and connection (key set, where to
 * get a key, Test connection, the Languages table) and the toolbar's Translate with Supertext… for editors.
 * Run it against a demo whose package talks to stand-in.mjs. See docs/DEVELOPER.md → Demo movie.
 *
 *   BASE_URL=http://127.0.0.1:8095 DEMO_ADMIN_EMAIL=… DEMO_ADMIN_PASSWORD=… npm run movie:install
 *
 * MOVIE_OUT: where the MP4 goes (default tests/docs/movie/out/djangoCMS-Supertext-Translation-install.mp4, git-ignored).
 * CHROMIUM_PATH: a Chromium to use instead of Playwright's.
 */
import { chromium } from 'playwright'
import { fileURLToPath } from 'node:url'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { MovieKit } from './movie/movie-kit.mjs'

const B = process.env.BASE_URL || 'http://127.0.0.1:8095'
const LIVE_API = 'https://api.supertext.com/v1/'
/** The public demo's domain, shown instead of the local one (as in the screenshots). */
const SITE_DOMAIN = process.env.SITE_DOMAIN || 'djangocms-production.up.railway.app'
const need = (name) => process.env[name] || (() => { throw new Error(`Set ${name}`) })()
const here = (p) => fileURLToPath(new URL(p, import.meta.url))
const mp4 = process.env.MOVIE_OUT || here('movie/out/djangoCMS-Supertext-Translation-install.mp4')
const workDir = mkdtempSync(join(tmpdir(), 'djangocms-install-movie-'))

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined })
const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1, locale: 'en-US' })
page.setDefaultTimeout(90_000)
// The movie runs locally against the stand-in: show the addresses users see instead of the local ones.
await page.addInitScript(({ live, site }) => {
  const fix = (root) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (!/127\.0\.0\.1|localhost/.test(n.textContent)) continue
      n.textContent = n.textContent
        .replace(/https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/v1\//g, live)
        .replace(/https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?/g, 'https://' + site)
    }
  }
  new MutationObserver(() => document.body && fix(document.body)).observe(document, { subtree: true, childList: true, characterData: true })
}, { live: LIVE_API, site: SITE_DOMAIN })

// Sign in as the administrator (not recorded).
await page.goto(`${B}/en/admin/login/`)
await page.fill('#id_username', need('DEMO_ADMIN_EMAIL'))
await page.fill('#id_password', need('DEMO_ADMIN_PASSWORD'))
await page.click('input[type=submit], button[type=submit]')
await page.waitForLoadState('networkidle')

const kit = await MovieKit.start(page, { workDir, assets: here('movie/assets'), voiceCache: here('movie/voice') })

/** Opens a page without recording the loading. */
const open = async (path, ready) => {
  kit.pause()
  await page.goto(B + path)
  await page.waitForLoadState('networkidle')
  if (ready) await ready()
  await page.waitForTimeout(1000)
  kit.resume()
}

// 1. Install (docs/INSTALLATION.md → Install).
await kit.say('First, install the Supertext package for django CMS. It isn’t on PyPI yet, so pip installs it straight from GitHub.', {
  caption: 'Install the package with <b>pip</b>',
  during: () => kit.terminal({
    title: 'my-site',
    lines: [
      { cmd: 'pip install git+https://github.com/Supertext/djangoCMS-Supertext-Translation.git' },
      { out: 'Collecting git+https://github.com/Supertext/djangoCMS-Supertext-Translation.git' },
      { out: 'Building wheels for collected packages: djangocms-supertext-translation', wait: 400 },
      { out: 'Successfully installed djangocms-supertext-translation-0.1.0' },
    ],
  }),
})

// 2. INSTALLED_APPS and the site's languages (→ Install, Languages).
await kit.say('In your settings, add djangocms_supertext to INSTALLED_APPS. Supertext translates between the languages your site already has, the ones in LANGUAGES.', {
  caption: 'Settings: add <b>djangocms_supertext</b> to <b>INSTALLED_APPS</b>',
  during: () => kit.terminal({
    title: 'my-site',
    lines: [
      { cmd: 'cat mysite/settings.py' },
      { out: 'INSTALLED_APPS = [' },
      { out: '    ...,' },
      { out: '    "djangocms_supertext",' },
      { out: '    "cms",' },
      { out: '    ...,' },
      { out: ']' },
      { out: 'LANGUAGES = [' },
      { out: '    ("en", "English"),' },
      { out: '    ("de-ch", "Deutsch (Schweiz)"),' },
      { out: '    ("fr-ch", "Français (Suisse)"),' },
      { out: '    ("it-ch", "Italiano (Svizzera)"),' },
      { out: ']' },
    ],
  }),
})

// 3. Migrate.
await kit.say('Then run migrate. It adds the package’s tables, for the translation log and the language settings.', {
  caption: 'Run <b>migrate</b>',
  during: () => kit.terminal({
    title: 'my-site',
    lines: [
      { cmd: 'python manage.py migrate djangocms_supertext' },
      { out: 'Running migrations:', wait: 300 },
      { out: '  Applying djangocms_supertext.0001_initial... OK' },
      { out: '  Applying djangocms_supertext.0002_state... OK' },
      { out: '  Applying djangocms_supertext.0003_language_setting... OK' },
      { out: '  Applying djangocms_supertext.0004_language_review... OK' },
    ],
  }),
})

// 4. The API key (→ API key).
await kit.say('Set your Supertext API key as the environment variable SUPERTEXT_API_KEY. supertext_check tests it.', {
  caption: 'Set <b>SUPERTEXT_API_KEY</b>, then <b>supertext_check</b>',
  during: () => kit.terminal({
    title: 'my-site',
    lines: [
      { cmd: 'export SUPERTEXT_API_KEY=st-demo-0000-0000-0000' },
      { cmd: 'python manage.py supertext_check' },
      { out: 'Version report to Supertext: sent.', wait: 400 },
      { out: `Connected to ${LIVE_API}. The API key works.` },
    ],
  }),
})

// 5. The settings page.
await open('/en/admin/', () => page.getByRole('link', { name: 'Supertext translations' }).first().waitFor())
await kit.say('Restart Django and open the admin. Under Supertext, open Supertext translations, then Settings and connection.', {
  caption: '<b>Supertext translations → Settings and connection</b>',
  during: async () => {
    await kit.click(page.getByRole('link', { name: 'Supertext translations' }).first())
    await page.waitForLoadState('networkidle')
    await kit.click(page.getByRole('link', { name: /Settings and connection/i }))
    await page.waitForLoadState('networkidle')
    await kit.moveTo(page.getByText('Set (environment variable SUPERTEXT_API_KEY)'))
  },
})
await kit.say('The API key is set. Generate yours at supertext.com, Integrations, API. No account yet? Create one at supertext.com.', {
  caption: 'Generate your API key at <b>supertext.com → Integrations → API</b>. No account yet? Create one at supertext.com.',
  during: () => kit.moveTo(page.locator('[data-supertext-key-help] a').nth(1)),
})
await kit.say('Click Test connection. The connection to Supertext works.', {
  caption: '<b>Test connection</b>: the API key works',
  during: async () => {
    await kit.click(page.getByRole('button', { name: 'Test connection' }))
    await page.waitForLoadState('networkidle')
    await kit.moveTo(page.locator('.messagelist li').first())
    await kit.hold(500)
  },
})

// 6. Languages.
await kit.say('Under Languages, each django CMS language gets a Supertext language. For German, Swiss German is chosen.', {
  caption: '<b>Languages</b>: the Supertext language for each language',
  during: async () => {
    await page.locator('[data-supertext-languages-heading]').evaluate((el) => el.scrollIntoView({ block: 'start', behavior: 'smooth' }))
    await page.waitForTimeout(900)
    const select = page.locator('select[name="target-de-ch"]')
    await kit.moveTo(select)
    await select.selectOption('de-CH')
    await kit.hold(600)
  },
})
await kit.say('Translation review can be ticked for each language. Leave it off for now.', {
  caption: '<b>Translation review</b>: optional, per language',
  during: () => kit.moveTo(page.locator('input[name="review-de-ch"]')),
})
await kit.say('Click Save languages, and they are saved.', {
  caption: 'Click <b>Save languages</b>',
  during: async () => {
    await kit.click(page.getByRole('button', { name: 'Save languages' }))
    await page.waitForLoadState('networkidle')
    await kit.moveTo(page.locator('.messagelist li').first())
  },
})

// 7. Where editors find it.
await open('/en/swiss-chocolate-shipped-worldwide/', async () => {
  const edit = await page.evaluate(() => [...document.querySelectorAll('a')].map((a) => a.getAttribute('href')).find((h) => h && /placeholder\/object\/\d+\/edit/.test(h)))
  if (!edit) throw new Error('No edit link for the sample page: run demo_setup first')
  await page.goto(B + edit)
  await page.waitForLoadState('networkidle')
})
await kit.say('Done. In edit mode, editors find Translate with Supertext in the toolbar’s Language menu.', {
  caption: 'Editors: <b>Language → Translate with Supertext…</b>',
  during: async () => {
    await kit.click(page.locator('.cms-toolbar-item-navigation > li > a', { hasText: 'Language' }).first())
    await page.waitForTimeout(400)
    await kit.moveTo(page.locator('.cms-toolbar-item-navigation a', { hasText: 'Translate with Supertext' }).first())
    await kit.hold(800)
  },
})
await kit.caption('')

await kit.finish(mp4, { system: 'django CMS', repo: 'djangoCMS-Supertext-Translation', kind: 'install' })
await browser.close()
rmSync(workDir, { recursive: true, force: true })
console.log(`Saved ${mp4}`)
