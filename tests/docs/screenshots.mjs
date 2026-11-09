#!/usr/bin/env node
/**
 * Regenerates docs/images from a freshly set-up demo (no translations yet) whose package
 * talks to stand-in.mjs (SUPERTEXT_API_URL=http://127.0.0.1:8765/v1/). See docs/DEVELOPER.md.
 *
 *   BASE_URL (default http://127.0.0.1:8095)
 *   DEMO_ADMIN_EMAIL / DEMO_ADMIN_PASSWORD     settings, page tree (superuser)
 *   DEMO_EDITOR_EMAIL / DEMO_EDITOR_PASSWORD   translating (Editors group)
 */
import { readFileSync } from 'node:fs'
import { chromium } from 'playwright'

const B = process.env.BASE_URL || 'http://127.0.0.1:8095'
const OUT = new URL('../../docs/images/', import.meta.url).pathname
const LIVE_API = 'https://api.supertext.com/v1/'
/** The public demo's domain, shown instead of the local one. */
const SITE_DOMAIN = process.env.SITE_DOMAIN || 'djangocms-production.up.railway.app'
const need = (name) => process.env[name] || (() => { throw new Error(`Set ${name}`) })()

const browser = await chromium.launch()

/** An exported HTML file "translated" with samples.json (what the translator would send back). */
const SAMPLES = JSON.parse(readFileSync(new URL('samples.json', import.meta.url), 'utf8'))
const norm = (s) => s.replace(/\s+/g, ' ').replace(/> </g, '><').trim()
const decode = (s) => s.replace(/&quot;/g, '"').replace(/&#0?39;|&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
const encode = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
function translateHtml(html, lang) {
  const known = new Map(Object.entries(SAMPLES[lang]).map(([k, v]) => [norm(k), v]))
  return html.replace(/(<div data-st-id="[^"]+">)([\s\S]*?)(<\/div>)/g, (all, open, inner, close) => {
    const hit = known.get(norm(inner)) ?? known.get(norm(decode(inner)))
    return hit === undefined ? all : open + (known.has(norm(inner)) ? hit : encode(hit)) + close
  })
}

async function session(email, password) {
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1, locale: 'en-US' })).newPage()
  await page.goto(`${B}/en/admin/login/`)
  await page.fill('#id_username', email)
  await page.fill('#id_password', password)
  await page.click('input[type=submit], button[type=submit]')
  await page.waitForLoadState('networkidle')
  return page
}

async function go(page, path) {
  await page.goto(B + path)
  await page.waitForLoadState('networkidle')
  await page.addStyleTag({ content: '*{animation:none!important;transition:none!important}' })
  await page.waitForTimeout(600)
}

async function shot(page, locator, name, margin = 0) {
  await locator.scrollIntoViewIfNeeded()
  const r = await locator.boundingBox()
  await page.screenshot({ path: OUT + name, clip: { x: Math.max(0, r.x - margin), y: Math.max(0, r.y - margin), width: r.width + 2 * margin, height: r.height + 2 * margin } })
}

async function openDialog(page) {
  await page.locator('.cms-toolbar-item-navigation > li > a', { hasText: 'Language' }).first().click()
  await page.locator('.cms-toolbar-item-navigation a', { hasText: 'Translate with Supertext' }).first().click()
  const frame = page.frameLocator('.cms-modal-frame iframe')
  await frame.locator('[data-supertext-form]').waitFor()
  await page.waitForTimeout(800)
  return frame
}

// --- Editor ------------------------------------------------------------------------------
{
  const page = await session(need('DEMO_EDITOR_EMAIL'), need('DEMO_EDITOR_PASSWORD'))
  await go(page, '/en/swiss-chocolate-shipped-worldwide/')
  const edit = await page.evaluate(() => [...document.querySelectorAll('a')].map((a) => a.getAttribute('href')).find((h) => h && /placeholder\/object\/\d+\/edit/.test(h)))
  await go(page, edit || '/en/swiss-chocolate-shipped-worldwide/')

  await page.locator('.cms-toolbar-item-navigation > li > a', { hasText: 'Language' }).first().click()
  await page.waitForTimeout(500)
  await page.screenshot({ path: OUT + '01-language-menu.png', clip: { x: 0, y: 0, width: 760, height: 240 } })
  await page.keyboard.press('Escape')
  await page.mouse.click(1000, 600)

  const modal = page.locator('.cms-modal')
  let frame = await openDialog(page)
  await shot(page, modal, '02-translate-dialog.png')

  await page.locator('.cms-modal-buttons a, .cms-modal-buttons input').filter({ hasText: 'Translate' }).first().click()
  await frame.locator('.st-results li').first().waitFor({ timeout: 60_000 })
  await page.waitForTimeout(600)
  await shot(page, modal, '03-translated.png')

  // Choosing a language that exists shows the overwrite warning.
  await frame.locator('input[name=targets][value="de-ch"]').check()
  await frame.locator('[data-supertext-warning]').waitFor({ state: 'visible' })
  await shot(page, modal, '04-overwrite-warning.png')
  await frame.locator('input[name=targets][value="de-ch"]').uncheck()

  // Export for translation (HTML into Italian), then import the translated file.
  const exportBox = frame.locator('#st-export')
  await exportBox.scrollIntoViewIfNeeded()
  await frame.locator('input[name="export-format"][value="html"]').check()
  await frame.locator('input[name="export-targets"][value="it-ch"]').check()
  await exportBox.screenshot({ path: OUT + '09-export.png' })
  const [download] = await Promise.all([page.waitForEvent('download'), exportBox.locator('input[type=submit]').click()])
  const exported = readFileSync(await download.path(), 'utf8')
  await frame.locator('input[name="import-file"]').setInputFiles({ name: download.suggestedFilename(), mimeType: 'text/html', buffer: Buffer.from(translateHtml(exported, 'it')) })
  await frame.locator('input[name="import-overwrite"]').check()
  await frame.locator('#st-import input[type=submit]').click()
  await frame.locator('.st-import-results').waitFor({ timeout: 60_000 })
  await page.waitForTimeout(600)
  await frame.locator('#st-import').screenshot({ path: OUT + '10-import-summary.png' })

  // The German page
  await go(page, '/de-ch/schweizer-schokolade-weltweit-versandt/')
  await page.screenshot({ path: OUT + '05-german-page.png', clip: { x: 240, y: 46, width: 800, height: 600 } })
}

// --- Admin -----------------------------------------------------------------------------
{
  const page = await session(need('DEMO_ADMIN_EMAIL'), need('DEMO_ADMIN_PASSWORD'))
  await go(page, '/en/admin/djangocms_supertext/translation/settings/')
  await page.locator('input[type=submit][value="Test connection"]').click()
  await page.waitForLoadState('networkidle')
  await page.evaluate(({ live, site }) => {
    document.querySelectorAll('[data-supertext-endpoint]').forEach((c) => { c.textContent = live })
    document.querySelectorAll('[data-supertext-domain]').forEach((c) => { c.textContent = site })
    document.querySelectorAll('[data-supertext-ping]').forEach((c) => { c.textContent = c.textContent.replace(/^https?:\/\/[^/]+/, 'https://' + site) })
  }, { live: LIVE_API, site: SITE_DOMAIN })
  const main = await page.locator('#content-main').boundingBox()
  const messages = await page.locator('.messagelist').boundingBox()
  await page.screenshot({ path: OUT + '06-settings.png', fullPage: true, clip: { x: main.x - 20, y: messages.y - 10, width: 800, height: main.y + main.height - messages.y + 30 } })
  // The Supertext languages: one select per django CMS language
  const languages = await page.locator('[data-supertext-languages]').boundingBox()
  const heading = await page.locator('[data-supertext-languages-heading]').boundingBox()
  await page.screenshot({ path: OUT + '08-languages.png', fullPage: true, clip: { x: languages.x - 10, y: heading.y - 10, width: Math.min(800, languages.width + 20), height: languages.y + languages.height - heading.y + 20 } })

  await go(page, '/en/admin/djangocms_supertext/translation/')
  await page.screenshot({ path: OUT + '07-translations-log.png', clip: { x: 0, y: 0, width: 1280, height: 460 } })
}

await browser.close()
console.log(`Screenshots written to ${OUT}`)
