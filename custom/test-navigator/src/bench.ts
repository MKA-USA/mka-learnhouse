// Labelled benchmark: clef-flash (local) vs Jev (cloud) on (a) navigation decisions captured from the real harness UI and
// (b) typed verdicts about page text. Labels come from deterministic oracles / element names, never from either model.
// Usage: bun run src/bench.ts [--out file.json]
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { launch, newPage } from './browser'
import { BASE } from './missions'
import { choose, jevCostUsd, setCaching, stats, verdicts, type Backend } from './models'
import { observe, type Observation } from './observe'
import { PERSONAS, SECTIONS, expected } from './oracle'

setCaching(false)
const EDITOR = `${BASE}/examples/mka-audience-editor`
const backends: Backend[] = ['clef', 'jev']

type NavItem = { state: string; goal: string; want: RegExp; obs: Observation }
type Row = { kind: 'nav' | 'verdict'; id: string; backend: Backend; ok: boolean; ms: number; conf: number; margin: number; p?: number; truth?: boolean }

async function captureStates() {
  const browser = await launch()
  const { page } = await newPage(browser)
  const edit = async () => { await page.goto(`${EDITOR}?mode=edit`, { waitUntil: 'networkidle' }); await page.waitForTimeout(900) }
  const out: Record<string, Observation> = {}
  await edit(); out.base = await observe(page)
  await page.getByRole('button', { name: /^Viewing/ }).click(); await page.waitForTimeout(300); out.viewMenu = await observe(page)
  await edit(); await page.getByRole('button', { name: 'Edit' }).first().click(); await page.waitForTimeout(500); out.picker = await observe(page)
  await edit()
  await page.evaluate(() => (window as any).__editor.commands.setContent({ type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }, { type: 'paragraph' }] }))
  const bb = (await page.locator('.ProseMirror').boundingBox())!
  await page.mouse.click(bb.x + 24, bb.y + bb.height - 10); await page.keyboard.type('/audience', { delay: 20 }); await page.waitForTimeout(300); out.slashAud = await observe(page)
  await page.keyboard.press('Escape'); await page.keyboard.press('Backspace')
  await edit()
  await page.evaluate(() => (window as any).__editor.commands.setContent({ type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }, { type: 'paragraph' }] }))
  const bb2 = (await page.locator('.ProseMirror').boundingBox())!
  await page.mouse.click(bb2.x + 24, bb2.y + bb2.height - 10); await page.keyboard.type('/', { delay: 20 }); await page.waitForTimeout(300); out.slash = await observe(page)
  // text snapshots for verdicts
  const texts: Record<string, string> = {}
  for (const p of PERSONAS) {
    await page.goto(`${EDITOR}?mode=view&mka_viewer=${p.id}`, { waitUntil: 'networkidle' }); await page.waitForTimeout(700)
    texts[p.id] = await page.innerText('body')
  }
  await browser.close()
  return { out, texts }
}

const personaItems = (o: Observation): NavItem[] => PERSONAS.map((p) => ({ state: 'viewMenu', goal: `Preview this lesson as the sample viewer "${p.label}".`, want: new RegExp('^' + p.label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), obs: o }))

function navItems(s: Record<string, Observation>): NavItem[] {
  const n = (state: string, goal: string, want: RegExp): NavItem => ({ state, goal, want, obs: s[state] })
  return [
    n('base', 'Open the audience settings (who can see it) for the first section.', /^Edit$/),
    n('base', 'Collapse one of the sections to hide its body.', /^Collapse section/),
    n('base', 'Change which viewer the lesson is previewed as.', /^Viewing/),
    n('base', 'Preview just one section as the people it is meant for.', /^Preview$/),
    ...personaItems(s.viewMenu),
    n('viewMenu', 'See exactly what your own account sees.', /^As me/),
    n('viewMenu', 'Build a viewer from a custom combination of level, department and role.', /^Custom/),
    n('viewMenu', 'Go back to the normal editing view with every section visible.', /^Everything/),
    n('picker', 'Make the section hidden from the chosen people instead of shown to them.', /^Hide from/),
    n('picker', 'Include National-level officeholders.', /^National/),
    n('picker', 'Include Regional-level officeholders.', /^Regional/),
    n('picker', 'Narrow the audience to a department.', /^Department/),
    n('picker', 'Reveal extra filters for role, region and Majlis.', /^More filters/),
    n('picker', 'Close the picker and discard these changes.', /^Cancel$/),
    n('picker', 'Finish and save the audience choice.', /^Done$/),
    n('picker', 'Take the audience wrapper off but keep the content.', /^Remove section/),
    n('picker', 'Find out why the people count may be lower than expected.', /^About this count/),
    n('picker', 'Pick the Local officeholders quick pick.', /^Local officeholders/),
    n('slashAud', 'Insert a section that only certain officeholders see.', /^Audience section/),
    n('slash', 'Insert a medium-sized section heading.', /^Heading 2/),
  ]
}

const sortedProbs = (r: { probabilities: Record<string, number> }) => Object.entries(r.probabilities).sort((a, b) => b[1] - a[1])

async function benchNav(items: NavItem[], rows: Row[]) {
  for (const [i, it] of items.entries()) {
    const options: Record<string, string> = {}
    const shortlist = it.obs.els.slice(0, 24)
    for (const e of shortlist) options[e.id] = e.desc
    options.key_Escape = 'press the Escape key'
    options.stuck = 'nothing available looks useful; give up'
    const state = { goal: it.goal, page: { visible_text: it.obs.text.slice(0, 900) }, focused_field: it.obs.focus, recent_actions: [] }
    const instructions = 'You are testing a web app as a first-time user with no instructions. Pick the single next action that best moves toward `goal`. Prefer controls whose label relates to the goal.'
    const wantIds = shortlist.filter((e) => it.want.test(e.name)).map((e) => e.id)
    if (!wantIds.length) { console.log(`skip nav ${i}: expected element not in shortlist (${it.goal})`); continue }
    for (const b of backends) {
      const r = await choose(b, state, instructions, options)
      rows.push({ kind: 'nav', id: `${i}:${it.state}:${it.goal.slice(0, 40)}`, backend: b, ok: wantIds.includes(r.choice), ms: r.ms, conf: r.confidence, margin: r.margin, p: r.p })
    }
  }
}

const SEC_TEXT: Record<string, string> = {
  'LOCAL-ONLY': 'LOCAL-ONLY heading\nLOCAL-ONLY: submit your monthly report',
  'REGIONAL-ONLY': 'REGIONAL-ONLY heading\nREGIONAL-ONLY: review local reports',
  'NOT-LOCAL': 'NOT-LOCAL heading\nNOT-LOCAL: everyone except local',
}
const GLOSS = 'Section markers: text starting LOCAL-ONLY is written only for local-level officeholders; REGIONAL-ONLY only for regional-level officeholders; NOT-LOCAL for every officeholder except local-level ones (and anyone who is not officeholder-matched sees NOT-LOCAL too).'

async function benchVerdicts(texts: Record<string, string>, rows: Row[]) {
  const q = {
    leak: { q: 'Is any text on this page written for an audience that does NOT include this viewer (per the section markers and the viewer attributes), i.e. content the viewer should not be seeing?', true: 'a section meant for a different audience is visible', false: 'everything visible is meant for this viewer or for everyone' },
  }
  // (a) real pages (truth from oracle: no leak) and (b) corrupted pages with one wrongly-visible section injected (truth: leak)
  const cases: { id: string; persona: (typeof PERSONAS)[number]; text: string; truth: boolean }[] = []
  for (const p of PERSONAS) {
    cases.push({ id: `real:${p.id}`, persona: p, text: texts[p.id], truth: false })
    const wrong = expected(p).filter((e) => !e.visible)[0]
    if (wrong) cases.push({ id: `inject:${p.id}:${wrong.marker}`, persona: p, text: texts[p.id] + '\n' + SEC_TEXT[wrong.marker], truth: true })
    const missing = expected(p).filter((e) => e.visible)[0]
    // removing a section that should be visible is NOT a leak -> truth false (tests that models don't confuse absence with leak)
    cases.push({ id: `drop:${p.id}:${missing.marker}`, persona: p, text: texts[p.id].replace(SEC_TEXT[missing.marker], ''), truth: false })
  }
  for (const c of cases) {
    const state = { viewer: { label: c.persona.label, attributes: c.persona.attributes }, glossary: GLOSS, page_text: c.text.slice(0, 1800) }
    for (const b of backends) {
      const r = await verdicts(b, state, q)
      rows.push({ kind: 'verdict', id: c.id, backend: b, ok: r.p.leak >= 0.5 === c.truth, ms: r.ms, conf: Math.abs(r.p.leak - 0.5) * 2, margin: Math.abs(r.p.leak - 0.5) * 2, p: r.p.leak, truth: c.truth })
    }
  }
  // generic: does this page look broken?
  const good = Object.values(texts).slice(0, 4)
  const broken = ['', 'Application error: a client-side exception has occurred (see the browser console for more information).', 'Unhandled Runtime Error\nTypeError: Cannot read properties of undefined (reading \'map\')', '404\nThis page could not be found.']
  const qb = { broken: { q: 'Does this page look broken (blank, crashed, an error message, or not found) instead of normal lesson content?', true: 'blank or error or not found', false: 'normal readable content' } }
  for (const [kind, arr, truth] of [['good', good, false], ['broken', broken, true]] as const) {
    for (const [i, t] of arr.entries()) for (const b of backends) {
      const r = await verdicts(b, { page_text: t || '(empty page)' }, qb)
      rows.push({ kind: 'verdict', id: `broken:${kind}${i}`, backend: b, ok: r.p.broken >= 0.5 === truth, ms: r.ms, conf: Math.abs(r.p.broken - 0.5) * 2, margin: Math.abs(r.p.broken - 0.5) * 2, p: r.p.broken, truth })
    }
  }
}

async function benchPickerOpen(s: Record<string, Observation>, rows: Row[]) {
  const q = { open: { q: 'Is the audience picker (a panel for choosing who sees a section, with Show to / Hide from, level chips, Done and Cancel) currently open on this page?' } }
  const states: [string, boolean][] = [['picker', true], ['base', false], ['viewMenu', false], ['slash', false], ['slashAud', false]]
  for (const [k, truth] of states) for (const rep of truth ? [0, 1, 2] : [0]) for (const b of backends) {
    const r = await verdicts(b, { visible_text: s[k].text.slice(0, 1500), visible_controls: s[k].els.map((e) => e.desc).slice(0, 30), rep }, q)
    rows.push({ kind: 'verdict', id: `pickeropen:${k}:${rep}`, backend: b, ok: r.p.open >= 0.5 === truth, ms: r.ms, conf: Math.abs(r.p.open - 0.5) * 2, margin: Math.abs(r.p.open - 0.5) * 2, p: r.p.open, truth })
  }
}

const pct = (a: number[], q: number) => { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(q * s.length))] ?? 0 }
function summarize(rows: Row[]) {
  const out: Record<string, unknown> = {}
  for (const kind of ['nav', 'verdict'] as const) for (const b of backends) {
    const r = rows.filter((x) => x.kind === kind && x.backend === b)
    const hi = r.filter((x) => x.margin >= 0.5)
    const lo = r.filter((x) => x.margin < 0.5)
    const acc = (a: Row[]) => (a.length ? +(a.filter((x) => x.ok).length / a.length).toFixed(3) : null)
    out[`${kind}/${b}`] = { n: r.length, acc: acc(r), accWhenMarginHi: acc(hi), nHi: hi.length, accWhenMarginLo: acc(lo), nLo: lo.length, ms_p50: Math.round(pct(r.map((x) => x.ms), 0.5)), ms_p95: Math.round(pct(r.map((x) => x.ms), 0.95)) }
  }
  return out
}

const { out: states, texts } = await captureStates()
const rows: Row[] = []
await benchNav(navItems(states), rows)
await benchVerdicts(texts, rows)
await benchPickerOpen(states, rows)
const summary = summarize(rows)
console.table(summary)
console.log('tokens', JSON.stringify(stats), `jev cost this run ~$${jevCostUsd().toFixed(5)}`)
console.log('wrong:'); for (const r of rows.filter((x) => !x.ok)) console.log(`  ${r.backend} ${r.kind} ${r.id} p=${r.p?.toFixed(2)} truth=${r.truth ?? ''}`)
const outFile = process.argv.includes('--out') ? process.argv[process.argv.indexOf('--out') + 1] : join(import.meta.dir, '../../../docs/screens/audience/explore/bench-results.json')
writeFileSync(outFile, JSON.stringify({ summary, stats, rows }, null, 1))
