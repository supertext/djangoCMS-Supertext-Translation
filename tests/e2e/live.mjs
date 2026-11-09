#!/usr/bin/env node
/**
 * End-to-end test against the REAL Supertext API: a fresh demo (nothing translated yet) with
 * a real SUPERTEXT_API_KEY. The editor opens every English page in edit mode and translates it
 * with the toolbar's Language → "Translate with Supertext" dialog into every other language,
 * then the database is checked: every page has a translated page content and text plugins in
 * each language, the texts are really in the target language (de-CH without "ß"), formatting
 * and links survived, the pages are reachable, and translating again (overwrite) updates the
 * page contents in place instead of duplicating them.
 * See "End-to-end tests" in docs/DEVELOPER.md.
 *
 *   DJANGOCMS_URL=http://127.0.0.1:8081 DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/djlive \
 *   EDITOR_EMAIL=… EDITOR_PASSWORD=… node tests/e2e/live.mjs
 */
import { chromium } from 'playwright';
import pg from 'pg';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const B = (process.env.DJANGOCMS_URL ?? 'http://127.0.0.1:8081').replace(/\/$/, '');
const SOURCE = process.env.E2E_SOURCE_LANGUAGE ?? 'en';
const need = (name) => process.env[name] || (() => { throw new Error(`Set ${name}`); })();
const artifacts = fileURLToPath(new URL('./artifacts/', import.meta.url));
mkdirSync(artifacts, { recursive: true });

const failures = [];
function check(name, ok, detail = '') {
	console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ` — ${detail}` : ''}`);
	if (!ok) failures.push(`${name}${detail ? ` — ${detail}` : ''}`);
	return ok;
}
const note = (text) => console.log(`note ${text}`);

// Common words, to tell the target languages apart. Lower case, whole words.
const STOPWORDS = {
	en: ['the', 'and', 'is', 'are', 'with', 'for', 'you', 'your', 'our', 'of', 'to', 'we', 'who', 'what'],
	de: ['der', 'die', 'das', 'und', 'ist', 'sind', 'mit', 'für', 'sie', 'ihre', 'ihr', 'unser', 'unsere', 'wir', 'eine', 'ein', 'den', 'zu', 'von', 'was'],
	fr: ['le', 'les', 'et', 'est', 'sont', 'avec', 'pour', 'vous', 'votre', 'vos', 'notre', 'nos', 'nous', 'des', 'une', 'un', 'du', 'de', 'qui', 'que'],
	it: ['il', 'lo', 'gli', 'e', 'è', 'sono', 'con', 'per', 'lei', 'sua', 'suo', 'nostro', 'nostra', 'noi', 'una', 'un', 'del', 'della', 'di', 'che', 'chi'],
};
const words = (text) => text.toLowerCase().match(/[\p{L}]+/gu) ?? [];
const score = (text, lang) => words(text).filter((w) => STOPWORDS[lang].includes(w)).length;
const plain = (v) => String(v ?? '').replace(/<[^>]+>/g, ' ');
const count = (haystack, needle) => String(haystack ?? '').split(needle).length - 1;

// Page content fields the plugin translates (translator.PAGE_FIELDS) and the text plugin's field.
const PAGE_FIELDS = ['title', 'page_title', 'menu_title', 'meta_description'];
const LEFTOVERS = ['data-st-id', 'data-st-ph', 'st-ph-', 'data-st-'];
// Markup that has to survive in a text plugin (opening tags, links with their address, inline plugins).
const MARKUP = [['bold', '<strong'], ['italics', '<em'], ['links', '<a '], ['headings', '<h2'], ['list items', '<li'], ['inline plugins', '<cms-plugin']];

const db = new pg.Client({ connectionString: need('DATABASE_URL') });
await db.connect();
const q = async (sql, params = []) => (await db.query(sql, params)).rows;

const [{ id: contentType }] = await q("SELECT id FROM django_content_type WHERE app_label = 'cms' AND model = 'pagecontent'");
const languages = (await q('SELECT DISTINCT language FROM cms_pageurl')).map((r) => r.language);

/** Everything of one language: page contents with their text plugins (by slot and position) and URLs. */
async function snapshot(language) {
	const contents = await q('SELECT * FROM cms_pagecontent WHERE language = $1 ORDER BY page_id', [language]);
	const plugins = await q(
		`SELECT ph.object_id AS content_id, ph.slot, p.id, p.plugin_type, p.position, p.parent_id, t.body
		   FROM cms_cmsplugin p
		   JOIN cms_placeholder ph ON ph.id = p.placeholder_id
		   LEFT JOIN djangocms_text_text t ON t.cmsplugin_ptr_id = p.id
		  WHERE p.language = $1 AND ph.content_type_id = $2
		  ORDER BY ph.slot, p.position`,
		[language, contentType],
	);
	const urls = await q('SELECT * FROM cms_pageurl WHERE language = $1', [language]);
	return contents.map((c) => ({
		...c,
		plugins: plugins.filter((p) => p.content_id === c.id),
		url: urls.find((u) => u.page_id === c.page_id),
		urls: urls.filter((u) => u.page_id === c.page_id).length,
	}));
}

// --- Setup -------------------------------------------------------------------------------
const source = await snapshot(SOURCE);
// The django CMS languages to translate into (E2E_LANGUAGES=de-ch,fr-ch,…); default: all the dialog offers.
const targets = (process.env.E2E_LANGUAGES ?? '').split(',').map((l) => l.trim()).filter((l) => l && l !== SOURCE);
console.log(`${SOURCE} source: ${source.length} pages, ${source.reduce((n, c) => n + c.plugins.length, 0)} plugins`);
check('demo has source pages', source.length > 0);
check('fresh demo (only the source language exists)', languages.length === 1 && languages[0] === SOURCE, languages.join(', '));

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, locale: 'en-US' });
page.setDefaultTimeout(30_000);

// --- Log in as the editor ----------------------------------------------------------------
await page.goto(`${B}/${SOURCE}/admin/login/`);
await page.fill('#id_username', need('EDITOR_EMAIL'));
await page.fill('#id_password', need('EDITOR_PASSWORD'));
await Promise.all([page.waitForNavigation(), page.click('input[type=submit], button[type=submit]')]);
if (!check('editor can log in (DEMO_EDITOR_*)', !page.url().includes('/login/'))) {
	await page.screenshot({ path: `${artifacts}login.png` });
	throw new Error(failures.join('\n'));
}

/** Opens the page in edit mode and the toolbar's Language → Translate with Supertext dialog. */
async function openDialog(content) {
	await page.goto(`${B}/${SOURCE}/admin/cms/placeholder/object/${contentType}/edit/${content.id}/`);
	await page.waitForLoadState('networkidle');
	await page.locator('.cms-toolbar-item-navigation > li > a', { hasText: 'Language' }).first().click();
	await page.locator('.cms-toolbar-item-navigation a', { hasText: 'Translate with Supertext' }).first().click();
	const frame = page.frameLocator('.cms-modal-frame iframe');
	await frame.locator('[data-supertext-form]').waitFor();
	return frame;
}

let demoTargets = targets;
async function translate(content, label, overwrite) {
	const tag = `${label}: "${content.title}"`;
	const frame = await openDialog(content);
	const offered = await frame.locator('input[name=targets]').evaluateAll((boxes) => boxes.map((b) => b.value));
	if (!demoTargets.length) demoTargets = offered.filter((l) => l !== SOURCE);
	const errorsBefore = await frame.locator('.errornote').allTextContents();
	check(`${tag}: dialog without errors`, errorsBefore.length === 0, errorsBefore.join(' | '));
	check(`${tag}: dialog offers every language`, demoTargets.every((l) => offered.includes(l)), offered.join(', '));
	for (const lang of demoTargets) await frame.locator(`input[name=targets][value="${lang}"]`).check();
	const warning = frame.locator('[data-supertext-warning]');
	if (overwrite) {
		check(`${tag}: overwrite warning shown`, await warning.isVisible());
		await frame.locator('#id_overwrite').check();
	} else {
		check(`${tag}: no overwrite warning (nothing translated yet)`, !(await warning.isVisible()));
	}
	const started = Date.now();
	await page.locator('.cms-modal-buttons a, .cms-modal-buttons input').filter({ hasText: 'Translate' }).first().click();
	await frame.locator('.st-results li, .errornote').first().waitFor({ timeout: 900_000 });
	await page.screenshot({ path: `${artifacts}${label}-page-${content.page_id}.png` });
	console.log(`${tag}: ${Math.round((Date.now() - started) / 1000)} s`);
	const results = await frame.locator('.st-results li').evaluateAll((items) => items.map((li) => ({ status: li.className, text: li.textContent.replace(/\s+/g, ' ').trim() })));
	const errors = await frame.locator('.errornote').allTextContents();
	const translated = results.filter((r) => r.status === 'translated');
	check(`${tag}: every language translated`, translated.length === demoTargets.length, `${translated.length}/${demoTargets.length}`);
	const expected = overwrite ? 'translation replaced' : 'translation created';
	check(`${tag}: results say "${expected}"`, translated.every((r) => r.text.includes(expected)), translated.map((r) => r.text).join(' | '));
	check(`${tag}: no errors from Supertext`, errors.length === 0 && results.every((r) => r.status !== 'error'),
		[...errors, ...results.filter((r) => r.status !== 'translated').map((r) => r.text)].map((e) => e.replace(/\s+/g, ' ').trim()).join(' | '));
}

// --- First translation -------------------------------------------------------------------
for (const content of source) await translate(content, 'first-run', false);
console.log(`Targets: ${demoTargets.join(', ')}`);
check('demo has target languages', demoTargets.length > 0);

const first = {};
for (const lang of demoTargets) {
	const t = (first[lang] = await snapshot(lang));
	const primary = lang.split(/[-_]/)[0].toLowerCase();
	check(`${lang}: every page translated`, source.every((s) => t.some((c) => c.page_id === s.page_id)), `${t.length}/${source.length}`);
	// No djangocms-versioning in the demo: django CMS shows a new language at once (with versioning the plugin
	// creates drafts; tests/test_versioning.py covers that).
	note(`${lang}: the demo has no djangocms-versioning, so translated languages are online at once`);

	let fields = 0;
	let changed = 0;
	let text = '';
	for (const s of source) {
		const c = t.find((x) => x.page_id === s.page_id);
		if (!c) continue;
		const tag = `${lang}: page ${s.page_id}`;
		for (const f of PAGE_FIELDS) {
			if (!String(s[f] ?? '').trim()) continue;
			fields++;
			const v = String(c[f] ?? '');
			if (!check(`${tag} ${f} filled`, v.trim() !== '', v)) continue;
			// A single word can be the same in the target language ("Home" in German); it counts against the ratio below.
			if (v !== s[f]) changed++;
			else note(`${tag} ${f} "${s[f]}" unchanged`);
			text += ` ${v}`;
			const left = LEFTOVERS.filter((l) => v.includes(l));
			check(`${tag} ${f} has no placeholders left`, left.length === 0, left.join(', '));
		}
		for (const name of ['template', 'in_navigation', 'soft_root']) {
			check(`${tag} keeps the page setting ${name}`, c[name] === s[name], `${c[name]} / ${s[name]}`);
		}
		check(`${tag} has a URL`, Boolean(c.url), c.url ? `/${lang}/${c.url.path}` : 'none');

		check(`${tag}: same plugins as the source`, c.plugins.map((p) => `${p.slot}:${p.plugin_type}`).join() === s.plugins.map((p) => `${p.slot}:${p.plugin_type}`).join(),
			`${c.plugins.length}/${s.plugins.length}`);
		check(`${tag}: source plugins untouched`, s.plugins.every((p) => !c.plugins.some((x) => x.id === p.id)));
		for (const [i, sp] of s.plugins.entries()) {
			const p = c.plugins[i];
			if (!p || sp.body == null || !plain(sp.body).trim()) continue;
			const where = `${tag} ${sp.plugin_type}#${sp.id}.body`;
			fields++;
			const v = String(p.body ?? '');
			if (!check(`${where} filled`, plain(v).trim() !== '')) continue;
			if (v !== sp.body) changed++;
			text += ` ${plain(v)}`;
			const left = LEFTOVERS.filter((l) => v.includes(l));
			check(`${where} has no placeholders left`, left.length === 0, left.join(', '));
			for (const [what, needle] of MARKUP) {
				if (count(sp.body, needle)) check(`${where} keeps its ${what}`, count(v, needle) === count(sp.body, needle), `${count(v, needle)}/${count(sp.body, needle)}`);
			}
			for (const [, href] of sp.body.matchAll(/href="([^"]+)"/g)) {
				check(`${where} keeps the link to ${href}`, v.includes(`href="${href}"`));
			}
		}
	}
	check(`${lang}: texts were changed by the translation`, fields > 0 && changed / fields >= 0.8, `${changed}/${fields} fields`);

	if (STOPWORDS[primary]) {
		const scores = Object.fromEntries(Object.keys(STOPWORDS).map((l) => [l, score(text, l)]));
		const best = Object.entries(scores).sort((a, b) => b[1] - a[1])[0][0];
		check(`${lang}: text is in the target language`, best === primary, JSON.stringify(scores));
	}
	if (/^de[-_]ch$/i.test(lang)) check(`${lang}: Swiss German spelling (no "ß")`, !text.includes('ß'));

	// The translated pages through the site itself.
	for (const c of t) {
		if (!c.url) continue;
		const res = await page.request.get(`${B}/${lang}/${c.url.path ? `${c.url.path}/` : ''}`);
		const html = await res.text();
		const body = c.plugins.find((p) => p.body)?.body ?? '';
		const firstWords = plain(body).trim().split(/\s+/).slice(0, 3).join(' ');
		check(`${lang}: page ${c.page_id} is shown at /${lang}/${c.url.path}`, res.status() === 200 && (!firstWords || plain(html).replace(/\s+/g, ' ').includes(firstWords)), `HTTP ${res.status()}`);
	}
}

// --- Translating again updates in place ---------------------------------------------------
for (const content of source) await translate(content, 'second-run', true);
for (const lang of demoTargets) {
	const second = await snapshot(lang);
	const ids = (rows) => rows.map((r) => r.id).sort((a, b) => a - b).join(',');
	check(`${lang}: translating again updates the page contents in place (no duplicates)`, ids(second) === ids(first[lang]), `${first[lang].length} → ${second.length}`);
	check(`${lang}: no duplicated URLs`, second.every((c) => c.urls === 1));
	for (const c of second) {
		const before = first[lang].find((x) => x.id === c.id);
		// Overwriting replaces the target's plugins with new translated copies (docs/DEVELOPER.md → Known
		// limitations), so plugin IDs change by design; their number must not grow.
		check(`${lang}: page ${c.page_id} has no duplicated plugins`, before && c.plugins.length === before.plugins.length, `${before?.plugins.length} → ${c.plugins.length}`);
		check(`${lang}: page ${c.page_id} still translated`, c.plugins.every((p) => !p.body || !LEFTOVERS.some((l) => p.body.includes(l))) && String(c.title).trim() !== '');
	}
}
check('source language untouched', JSON.stringify((await snapshot(SOURCE)).map((c) => [c.id, c.title, c.plugins.map((p) => [p.id, p.body])])) === JSON.stringify(source.map((c) => [c.id, c.title, c.plugins.map((p) => [p.id, p.body])])));

const log = await q("SELECT status, COUNT(*)::int AS n FROM djangocms_supertext_translation GROUP BY status ORDER BY status");
check('translation log: only successful translations', log.every((r) => r.status === 'translated'), JSON.stringify(log));

await browser.close();
await db.end();

if (failures.length) {
	console.error(`\n${failures.length} check(s) failed:\n- ${failures.join('\n- ')}`);
	process.exit(1);
}
console.log('\nAll end-to-end checks passed.');
