#!/usr/bin/env node
/**
 * Records the README's demo movie (docs/images/demo.gif, plus a narrated MP4 that isn't committed)
 * with the shared Supertext movie kit (movie/movie-kit.mjs), as the demo's editor: the sample page
 * in English in edit mode, the toolbar's Language → Translate with Supertext…, Translate, the waiting
 * state, the results and the German page. Run it against a fresh demo (the page must have no
 * translations yet) whose package talks to stand-in.mjs. See docs/DEVELOPER.md → Demo movie.
 *
 *   BASE_URL=http://127.0.0.1:8095 DEMO_EDITOR_EMAIL=… DEMO_EDITOR_PASSWORD=… npm run movie
 *
 * MOVIE_OUT: where the MP4 goes (default tests/docs/movie/out/djangoCMS-Supertext-Translation.mp4, git-ignored).
 * CHROMIUM_PATH: a Chromium to use instead of Playwright's.
 */
import { chromium } from 'playwright'
import { fileURLToPath } from 'node:url'
import { mkdtempSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { MovieKit } from './movie/movie-kit.mjs'

const B = process.env.BASE_URL || 'http://127.0.0.1:8095'
const need = (name) => process.env[name] || (() => { throw new Error(`Set ${name}`) })()
const here = (p) => fileURLToPath(new URL(p, import.meta.url))
const mp4 = process.env.MOVIE_OUT || here('movie/out/djangoCMS-Supertext-Translation.mp4')
const gif = here('../../docs/images/demo.gif')
const workDir = mkdtempSync(join(tmpdir(), 'djangocms-movie-'))

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined })
const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1, locale: 'en-US' })
page.setDefaultTimeout(90_000)

// Sign in as the editor and open the sample page in edit mode (not recorded).
await page.goto(`${B}/en/admin/login/`)
await page.fill('#id_username', need('DEMO_EDITOR_EMAIL'))
await page.fill('#id_password', need('DEMO_EDITOR_PASSWORD'))
await page.click('input[type=submit], button[type=submit]')
await page.waitForLoadState('networkidle')
await page.goto(`${B}/en/swiss-chocolate-shipped-worldwide/`)
await page.waitForLoadState('networkidle')
const edit = await page.evaluate(() => [...document.querySelectorAll('a')].map((a) => a.getAttribute('href')).find((h) => h && /placeholder\/object\/\d+\/edit/.test(h)))
if (!edit) throw new Error('No edit link for the sample page: run demo_setup and sign in as the editor')
await page.goto(B + edit)
await page.waitForLoadState('networkidle')
await page.waitForTimeout(800)

const kit = await MovieKit.start(page, { workDir, assets: here('movie/assets'), voiceCache: here('movie/voice') })
const frame = page.frameLocator('.cms-modal-frame iframe')

// 1. The page in English.
await kit.say("Here's a page in django CMS, written in English.", {
  caption: 'A page in English',
  during: async () => {
    await kit.hold(500)
    await kit.moveTo(page.getByText('From Bern to the world').first())
    await kit.hold(500)
  },
})

// 2. Toolbar: Language → Translate with Supertext…
await kit.say('In the toolbar, open the Language menu and choose Translate with Supertext.', {
  caption: 'Toolbar: <b>Language → Translate with Supertext…</b>',
  during: async () => {
    await kit.click(page.locator('.cms-toolbar-item-navigation > li > a', { hasText: 'Language' }).first())
    await page.waitForTimeout(400)
    await kit.click(page.locator('.cms-toolbar-item-navigation a', { hasText: 'Translate with Supertext' }).first())
    await frame.locator('[data-supertext-form]').waitFor()
    await page.waitForTimeout(600)
  },
})

// 3. The dialog: languages ticked, Translate.
await kit.say('German, French and Italian are already ticked. Click Translate.', {
  caption: 'German, French and Italian are ticked: click <b>Translate</b>',
  during: async () => {
    await kit.moveTo(frame.locator('label[for="st-de-ch"]'))
    await kit.hold(500)
    // The translation runs inside this request: don't let Playwright wait for it here.
    await kit.click(page.locator('.cms-modal-buttons a, .cms-modal-buttons input').filter({ hasText: 'Translate' }).first(), { noWaitAfter: true })
  },
})

// 4. Waiting (cut).
await kit.say('Supertext translates the content.', { caption: 'Supertext translates the content…', during: () => kit.hold(1200) })
kit.pause()
await frame.locator('.st-results li').first().waitFor({ timeout: 180_000 })
await page.waitForTimeout(600)
kit.resume()

// 5. The results.
await kit.say('A few seconds later, all three languages are ready.', {
  caption: 'German, French and Italian are ready',
  during: () => kit.moveTo(frame.locator('.st-results li').first()),
})

// 6. The German page.
await kit.say('Open the German version to review it.', {
  caption: 'Click <b>Open</b> next to Deutsch (Schweiz)',
  during: async () => {
    await kit.click(frame.locator('.st-results li').filter({ hasText: 'Deutsch' }).getByRole('link', { name: 'Open' }))
    await page.waitForLoadState('networkidle')
    await page.getByText('Von Bern in die Welt').first().waitFor()
    await page.waitForTimeout(600)
  },
})
await kit.say('Here it is, in German. Review it, and change what you like, just like your own text.', {
  caption: 'The German version is ready – review it',
  during: async () => {
    await kit.moveTo(page.getByText('Von Bern in die Welt').first())
    await kit.hold(600)
    await kit.moveTo(page.getByText('Klimaneutrale Lieferung').first())
  },
})
await kit.caption('')

await kit.finish(mp4, { system: 'django CMS', repo: 'djangoCMS-Supertext-Translation', gif })
await browser.close()
rmSync(workDir, { recursive: true, force: true })
console.log(`Saved ${mp4} and ${gif} (${(statSync(gif).size / 1e6).toFixed(2)} MB)`)
