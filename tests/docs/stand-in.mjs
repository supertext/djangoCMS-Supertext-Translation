#!/usr/bin/env node
/**
 * Docs screenshots and CI only: answers like the Supertext AI file translation API v1 and
 * returns German, French and Italian for the demo's sample article (samples.json: real
 * Supertext output, keyed by target language's primary subtag).
 * Unknown text comes back as "[<target>] text". Listens on :8765 (any API key).
 *
 * STAND_IN_DELAY=<seconds>: files stay `in_progress` that long (the demo movie shows the waiting state).
 */
import http from 'node:http'
import { randomBytes } from 'node:crypto'
import { readFileSync } from 'node:fs'

const norm = (s) => s.replace(/\s+/g, ' ').replace(/> </g, '><').trim()
const decode = (s) => s.replace(/&quot;/g, '"').replace(/&#0?39;|&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
const encode = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const samples = Object.fromEntries(
  Object.entries(JSON.parse(readFileSync(new URL('samples.json', import.meta.url), 'utf8'))).map(([lang, pairs]) => [
    lang,
    new Map(Object.entries(pairs).map(([k, v]) => [norm(k), v])),
  ]),
)
const files = new Map()
const delayMs = Number(process.env.STAND_IN_DELAY || 0) * 1000
// Exactly the target codes the live API accepts (the SDK's Languages.TARGETS, GET features, October 2026);
// false: no formal/informal for that target.
const TARGETS = {
  bg: true, cs: true, da: true, 'de-AT': true, 'de-CH': true, 'de-DE': true, el: true, 'en-GB': false, 'en-US': false,
  es: true, fi: true, 'fr-CH': true, 'fr-FR': true, 'gsw-u-sd-chbe': false, 'gsw-u-sd-chzh': false, hr: true, hu: true,
  'it-CH': true, 'it-IT': true, ja: true, ko: true, nb: true, nl: true, pl: true, 'pt-BR': true, 'pt-PT': true, rm: false,
  ru: true, sk: true, sl: true, sq: false, 'sr-Cyrl': false, 'sr-Latn': false, sv: true, tr: true, 'zh-Hans': true, 'zh-Hant': true,
}
// Stands in for the Commando Center too (SUPERTEXT_REPORT_URL=http://127.0.0.1:8765/report), so the demo and
// the screenshots never report to the live center; GET /reports lists what was received (CI checks it).
const reports = []

http
  .createServer(async (req, res) => {
    const path = new URL(req.url, 'http://x').pathname.replace(/^\/v1/, '')
    const send = (status, body, type = 'application/json') => {
      res.writeHead(status, { 'Content-Type': type })
      res.end(type === 'application/json' ? JSON.stringify(body) : body)
    }
    if (req.method === 'POST' && path === '/report') {
      const chunks = []
      for await (const chunk of req) chunks.push(chunk)
      reports.push(JSON.parse(Buffer.concat(chunks).toString('utf8')))
      return send(202, { ok: true })
    }
    if (req.method === 'GET' && path === '/reports') return send(200, reports)
    if (!/^Supertext-Auth-Key \S+$/.test(req.headers.authorization || '')) return send(401, { detail: 'missing key' })
    if (path === '/features') return send(200, {})
    if (req.method === 'POST') {
      const chunks = []
      for await (const chunk of req) chunks.push(chunk)
      const form = await new Request('http://x', { method: 'POST', headers: req.headers, body: Buffer.concat(chunks) }).formData()
      const file = form.get('file')
      if (!file || file.type !== 'text/html') return send(415, { detail: 'FILETYPE_NOT_ALLOWED' })
      const target = String(form.get('target_lang'))
      // Like the live API: only its exact codes ("de" or "es-ES" are not valid pairs: HTTP 404).
      if (!(target in TARGETS)) {
        return send(404, { error_code: 'INVALID_LANGUAGE_PAIR', source_lang: form.get('source_lang'), target_lang: target })
      }
      if (form.get('politeness') && !TARGETS[target]) {
        return send(400, { error_code: 'FEATURE_ERROR', source_lang: form.get('source_lang'), target_lang: target })
      }
      const id = randomBytes(6).toString('hex')
      files.set(id, { html: await file.text(), target, at: Date.now() })
      return send(200, { file_id: id })
    }
    const match = path.match(/file\/([a-f0-9]+)(\/status|\/translation)?$/)
    const file = match && files.get(match[1])
    if (!file) return send(404, {})
    if (req.method === 'DELETE') { files.delete(match[1]); return send(200, {}) }
    if (match[2] === '/status') return send(200, { status: Date.now() - file.at < delayMs ? 'in_progress' : 'done' })
    const known = samples[file.target.split('-')[0]] ?? new Map()
    const html = file.html.replace(/(<div data-st-id="\d+">)([\s\S]*?)(<\/div>\n)/g, (all, open, inner, close) => {
      const hit = known.get(norm(inner)) ?? known.get(norm(decode(inner)))
      if (hit !== undefined) return open + (known.has(norm(inner)) ? hit : encode(hit)) + close
      return open + inner.replace(/>([^<]+)</g, (m, t) => (t.trim() ? `>[${file.target}] ${t}<` : m)).replace(/^([^<]+)/, `[${file.target}] $1`) + close
    })
    send(200, html, 'text/html')
  })
  .listen(Number(process.env.PORT || 8765), '127.0.0.1', () => console.log(`Stand-in API on http://127.0.0.1:${process.env.PORT || 8765}/v1/`))
