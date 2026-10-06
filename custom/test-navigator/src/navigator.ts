// Mission runner: deterministic Playwright executes; a typed-decision model picks the next action among enumerated ids.
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Page } from 'playwright-core'
import { choose, verdicts, type Backend } from './models'
import { observe, type El, type Observation } from './observe'

export type Step =
  | { t: 'click'; css: string; label: string }
  | { t: 'type'; text: string; label: string }
  | { t: 'press'; key: string }
  | { t: 'resize'; w: number; h: number }
  | { t: 'goto'; url: string }
export type Issue = { step: number; kind: string; detail: string; shot?: string }
export type Mission = {
  id: string
  goal: string
  url: string
  viewport?: { width: number; height: number }
  maxSteps: number
  maxCalls: number
  inputs: string[] // candidate strings the model may choose to type (generic, no hints about the feature)
  keys?: string[]
  setup?: (page: Page) => Promise<void>
  success?: (page: Page) => Promise<{ ok: boolean; detail: string }>
  /** deterministic end-of-mission oracle checks (run once after the loop) */
  post?: (page: Page) => Promise<Array<{ kind: string; detail: string }>>
  invariants?: (page: Page, obs: Observation) => Promise<Array<{ kind: string; detail: string }>>
  /** probability of taking a random enumerated action instead of the model's pick (exploration). */
  epsilon?: number
  /** element names the runner must never offer (keeps read-only runs read-only) */
  deny?: RegExp
  storageState?: string
}
export type StepLog = {
  n: number; url: string; action: string; backend: Backend | 'random' | 'guard'; confidence: number; p: number; margin: number
  ms: number; escalated: boolean; changed: boolean; shot: string; cached: boolean
}
export type Result = {
  mission: string; ok: boolean; detail: string; steps: number; modelCalls: number; wallMs: number; modelMs: number
  trace: Step[]; log: StepLog[]; issues: Issue[]; stoppedBy: 'success' | 'done' | 'stuck' | 'max-steps' | 'max-calls'
}
export type Opts = { sanity?: Backend; primary: Backend; fallback?: Backend; minMargin: number; outDir: string; seed?: number; screenshots?: boolean }

const MAX_OPTIONS = 26
const DEFAULT_KEYS = ['Escape', 'Enter', 'Tab', 'ArrowDown']

function rng(seed: number) {
  let s = seed >>> 0
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32)
}
const fingerprint = (o: Observation) => `${o.url}|${o.dialogOpen}|${o.text.length}|${o.text.slice(0, 400)}|${o.els.map((e) => e.desc).join(';')}`

export async function exec(page: Page, s: Step) {
  switch (s.t) {
    case 'click': {
      const loc = page.locator(s.css).first()
      if (s.css.includes('ProseMirror') || /contenteditable/.test(s.css)) {
        const box = await loc.boundingBox()
        if (box) { await page.mouse.click(box.x + 24, box.y + box.height - 10); break }
      }
      await loc.click({ timeout: 3000 })
      break
    }
    case 'type': await page.keyboard.type(s.text, { delay: 15 }); break
    case 'press': await page.keyboard.press(s.key); break
    case 'resize': await page.setViewportSize({ width: s.w, height: s.h }); break
    case 'goto': await page.goto(s.url, { waitUntil: 'networkidle' }); break
  }
  await page.waitForTimeout(250)
}

export function globalInvariants(page: Page, obs: Observation, prevTextLen: number) {
  return page
    .evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: innerWidth, err: !!document.querySelector('nextjs-portal')?.shadowRoot?.querySelector('[data-nextjs-dialog]') }))
    .then((r) => {
      const out: Array<{ kind: string; detail: string }> = []
      if (r.sw > r.iw + 1) out.push({ kind: 'h-overflow', detail: `page scrollWidth ${r.sw} > viewport ${r.iw}` })
      if (r.err || /Unhandled Runtime Error|Application error: a client-side exception/.test(obs.text)) out.push({ kind: 'error-overlay', detail: 'framework error overlay / crash text visible' })
      const bad = obs.text.match(/\b(undefined|NaN|\[object Object\]|null)\b/)
      if (bad) out.push({ kind: 'bad-text', detail: `visible text contains "${bad[0]}"` })
      if (prevTextLen > 80 && obs.text.length < 20) out.push({ kind: 'blank-page', detail: `visible text dropped from ${prevTextLen} to ${obs.text.length} chars` })
      return out
    })
}

export async function runMission(page: Page, m: Mission, o: Opts): Promise<Result> {
  const dir = join(o.outDir, m.id)
  mkdirSync(dir, { recursive: true })
  const rand = rng(o.seed ?? 1)
  const issues: Issue[] = []
  const trace: Step[] = []
  const log: StepLog[] = []
  let modelCalls = 0
  let modelMs = 0
  const t0 = Date.now()
  const errs: string[] = []
  page.on('pageerror', (e) => errs.push(`pageerror: ${e.message.slice(0, 200)}`))
  page.on('response', (r) => { if (r.status() >= 400 && !/favicon|hot-update|__nextjs|\.map$|webpack|_next\/static/.test(r.url())) errs.push(`http ${r.status()} ${r.request().method()} ${r.url().replace(/^https?:\/\/[^/]+/, '').slice(0, 120)}`) })
  page.on('console', (c) => { if (c.type() === 'error' && !/favicon|Download the React DevTools|hydrat|Failed to load resource/i.test(c.text())) errs.push(`console.error: ${c.text().slice(0, 200)}`) })

  if (m.viewport) await page.setViewportSize(m.viewport)
  await page.goto(m.url, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  if (m.setup) await m.setup(page)
  let obs = await observe(page)
  const visited = new Set<string>([fingerprint(obs)])
  const tried = new Map<string, Set<string>>() // fingerprint -> action keys already tried without effect
  const history: string[] = []
  let stoppedBy: Result['stoppedBy'] = 'max-steps'
  let ok = false
  let detail = 'budget exhausted'
  const keys = m.keys ?? DEFAULT_KEYS
  let falseDone = false

  for (let n = 1; n <= m.maxSteps; n++) {
    if (m.success) {
      const s = await m.success(page)
      if (s.ok) { ok = true; detail = s.detail; stoppedBy = 'success'; break }
    }
    const fp = fingerprint(obs)
    const triedHere = tried.get(fp) ?? new Set<string>()
    const options: Record<string, string> = {}
    const extra: Record<string, string> = {}
    if (obs.focus) m.inputs.forEach((v, i) => { if (!triedHere.has(`t:${i}`)) extra[`type_${i}`] = `type ${JSON.stringify(v)} into ${obs.focus}` })
    for (const k of keys) if (!triedHere.has(`k:${k}`)) extra[`key_${k}`] = `press the ${k} key`
    if (!falseDone) extra.done = 'the goal is already achieved on screen'
    if (n >= 8) extra.stuck = 'nothing available looks useful; give up'
    // clef-flash accepts at most 26 options per choice: shortlist elements deterministically (goal-word overlap,
    // later DOM order wins ties because popovers/portals render last). The model still chooses among the shortlist.
    const goalWords = new Set(`${m.goal} ${history.slice(-1)[0] ?? ''}`.toLowerCase().match(/[a-z]{3,}/g) ?? [])
    const cand = obs.els
      .map((e, i) => ({ e, i, score: (e.name.toLowerCase().match(/[a-z]{3,}/g) ?? []).filter((w) => goalWords.has(w)).length }))
      .filter((x) => !triedHere.has(`c:${x.e.id}:${x.e.desc}`) && !(m.deny && m.deny.test(x.e.name)))
      .sort((a, b) => b.score - a.score || b.i - a.i)
      .slice(0, Math.max(1, MAX_OPTIONS - Object.keys(extra).length))
      .sort((a, b) => a.i - b.i)
    for (const x of cand) options[x.e.id] = x.e.desc
    Object.assign(options, extra)

    let pick = ''
    let meta = { backend: 'guard' as StepLog['backend'], confidence: 0, p: 0, margin: 0, ms: 0, escalated: false, cached: false }
    if (modelCalls >= m.maxCalls) { stoppedBy = 'max-calls'; detail = 'model-call budget exhausted'; break }
    if (m.epsilon && rand() < m.epsilon) {
      const ids = Object.keys(options).filter((k) => k !== 'done' && k !== 'stuck')
      pick = ids[Math.floor(rand() * ids.length)]
      meta.backend = 'random'
    } else {
      const state = {
        goal: m.goal,
        step: n,
        page: { url: obs.url, title: obs.title, visible_text: obs.text.slice(0, 900) },
        focused_field: obs.focus,
        recent_actions: history.slice(-5),
      }
      const instructions = 'You are testing a web app as a first-time user with no instructions. Pick the single next action that best moves toward `goal`. Prefer controls whose label relates to the goal; avoid repeating actions that already had no effect. Choose done only if the goal is visibly achieved.'
      let r = await choose(o.primary, state, instructions, options)
      modelCalls++; modelMs += r.ms
      meta = { backend: o.primary, confidence: r.confidence, p: r.p, margin: r.margin, ms: r.ms, escalated: false, cached: r.cached }
      if (o.fallback && r.margin < o.minMargin && modelCalls < m.maxCalls) {
        const r2 = await choose(o.fallback, state, instructions, options)
        modelCalls++; modelMs += r2.ms
        r = r2
        meta = { backend: o.fallback, confidence: r2.confidence, p: r2.p, margin: r2.margin, ms: meta.ms + r2.ms, escalated: true, cached: r2.cached }
      }
      pick = r.choice
    }
    if (pick === 'done') {
      const s = m.success ? await m.success(page) : { ok: true, detail: 'model declared done' }
      if (s.ok) { stoppedBy = 'done'; ok = true; detail = s.detail; break }
      falseDone = true; history.push(`you said done but the goal is NOT met yet (${s.detail.slice(0, 80)})`); continue
    }
    if (pick === 'stuck') { stoppedBy = 'stuck'; detail = 'model gave up'; break }

    let step: Step
    let label: string
    let akey: string
    if (pick.startsWith('key_')) {
      step = { t: 'press', key: pick.slice(4) }; label = `press ${pick.slice(4)}`; akey = `k:${pick.slice(4)}`
    } else if (pick.startsWith('type_')) {
      const text = m.inputs[Number(pick.slice(5))]
      step = { t: 'type', text, label: `type ${JSON.stringify(text)}` }; label = step.label; akey = `t:${pick.slice(5)}`
    } else {
      const el = obs.els.find((e) => e.id === pick) as El
      label = el.desc; akey = `c:${el.id}:${el.desc}`
      step = { t: 'click', css: el.css, label }
    }
    let err = ''
    try { await exec(page, step) } catch (e) { err = (e as Error).message.split('\n')[0] }
    trace.push(step)
    history.push(`${label}${err ? ` (failed: ${err.slice(0, 60)})` : ''}`)
    const prevLen = obs.text.length
    const next = await observe(page)
    const changed = fingerprint(next) !== fp
    // cycle guard: an action that merely returns to an already-visited state counts as tried (stops '/' <-> Escape loops)
    if (changed && visited.has(fingerprint(next))) { triedHere.add(akey); tried.set(fp, triedHere) }
    visited.add(fingerprint(next))
    if (!changed) { triedHere.add(akey); tried.set(fp, triedHere); history[history.length - 1] += ' (no visible change)' }
    obs = next
    const shot = `step-${String(n).padStart(2, '0')}.jpg`
    if (o.screenshots !== false) await page.screenshot({ path: join(dir, shot), type: 'jpeg', quality: 55 })
    log.push({ n, url: obs.url, action: label, ...meta, changed, shot })
    const found = [...(await globalInvariants(page, obs, prevLen)), ...(m.invariants ? await m.invariants(page, obs) : [])]
    while (errs.length) found.push({ kind: 'js-error', detail: errs.shift() as string })
    if (o.sanity && changed && modelCalls < m.maxCalls + 30) {
      try {
        const v = await verdicts(o.sanity, { page_text: obs.text.slice(0, 1500), controls: obs.els.map((e) => e.desc).slice(0, 30), last_action: label }, { odd: { q: 'Does this UI state look wrong or broken for a polished form/editor (e.g. contradictory text, raw data or placeholders leaking, an empty control that should have content, error text, unreadable layout)?', true: 'visibly wrong, contradictory or broken', false: 'looks normal' } })
        if (v.p.odd >= 0.9) found.push({ kind: 'model-flag', detail: `${o.sanity} p=${v.p.odd.toFixed(2)} after "${label}": ${obs.text.replace(/\s+/g, ' ').slice(0, 140)}` })
      } catch { /* sanity is best-effort */ }
    }
    for (const f of found) issues.push({ step: n, ...f, shot })
  }
  if (!m.success && m.maxSteps === 0) { ok = !issues.some((i) => i.kind !== 'js-error') ; detail = ok ? 'oracle check passed' : 'oracle mismatch'; stoppedBy = 'done' }
  if (m.success && !ok) { const s = await m.success(page); ok = s.ok; if (ok) { detail = s.detail; stoppedBy = 'success' } else if (stoppedBy !== 'max-steps' && stoppedBy !== 'max-calls') detail += ` | final check: ${s.detail}` }
  if (m.post) for (const f of await m.post(page)) issues.push({ step: trace.length, ...f })
  const res: Result = { mission: m.id, ok, detail, steps: trace.length, modelCalls, wallMs: Date.now() - t0, modelMs, trace, log, issues, stoppedBy }
  writeFileSync(join(dir, 'trace.json'), JSON.stringify(res, null, 1))
  return res
}
