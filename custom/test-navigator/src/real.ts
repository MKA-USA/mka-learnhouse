// Phase 2: the same checks against a REAL local stack (real API). Read-only: learner pages + the author editor with write-ish
// controls denied, and the lesson content is hashed before/after to prove nothing changed.
// Usage: bun run src/real.ts [stack.json] [--primary clef|jev] [--fallback jev|none]
import { createHash } from 'node:crypto'
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { launch } from './browser'
import { evaluateRule } from '../../../apps/web/components/mka/audience/evaluate'
import { describeRule } from '../../../apps/web/components/mka/audience/describe'
import { MOCK_OPTIONS } from '../../../apps/web/app/examples/mka-audience-playground/mock-options'
import { jevCostUsd, stats, useCache, verdicts, type Backend } from './models'
import { runMission, type Mission, type Result } from './navigator'

const argv = process.argv.slice(2)
const flag = (n: string, d: string) => { const i = argv.indexOf(`--${n}`); return i >= 0 ? argv[i + 1] : d }
const stackFile = argv.find((a, i) => !a.startsWith('--') && !argv[i - 1]?.startsWith('--')) ?? '/private/tmp/claude-501/mka-e2e-stack.json'
if (!existsSync(stackFile)) { console.error(`no stack file at ${stackFile}`); process.exit(2) }
const stack = JSON.parse(readFileSync(stackFile, 'utf8'))
const P = JSON.parse(readFileSync(stack.personasFile, 'utf8'))
const OUT = join(import.meta.dir, '../../../docs/screens/audience/explore/real')
mkdirSync(OUT, { recursive: true })
useCache(join(OUT, '../.decision-cache.json'))
const primary = flag('primary', 'clef') as Backend
const fb = flag('fallback', 'jev')

type Sec = { token: string; rule: any }
const browser = await launch()
const admin = await browser.newContext({ storageState: P.personas.admin.storageState })
const getContent = async () => (await (await admin.request.get(`${P.apiV1}/activities/${P.activityUuid}`)).json()).content
const content0 = await getContent()
const hash0 = createHash('sha256').update(JSON.stringify(content0)).digest('hex')
const sections: Sec[] = []
const walk = (n: any) => { if (n?.type === 'mkaAudience') sections.push({ token: (JSON.stringify(n).match(/ZQ-BODY-[A-Z0-9]+-[a-z0-9]+/) ?? ['?'])[0], rule: n.attrs.rule }); (n?.content ?? []).forEach(walk) }
walk(content0)
const issues: Array<{ mission: string; kind: string; detail: string }> = []
const rows: any[] = []

// 1. Learner pages: oracle (product evaluator over the persona's real /me attributes) vs rendered DOM, + model verdicts.
for (const [key, persona] of Object.entries<any>(P.personas)) {
  const ctx = await browser.newContext({ storageState: persona.storageState, viewport: { width: 1280, height: 900 } })
  const me = await (await ctx.request.get(`${P.apiV1}/mka/attributes/me?course_uuid=${P.courseUuid}`)).json()
  const attrs = me.attributes
  const page = await ctx.newPage()
  const t0 = Date.now()
  await page.goto(P.learnerUrl, { waitUntil: 'networkidle' }); await page.waitForTimeout(2500)
  const text = await page.innerText('body')
  await page.screenshot({ path: join(OUT, `learner-${key}.jpg`), type: 'jpeg', quality: 55 })
  const bad: string[] = []
  for (const s of sections) {
    const want = me.can_view_all ? true : evaluateRule(s.rule, attrs) // can_view_all viewers see every section by design (contract 3.3)
    const shown = text.includes(s.token)
    if (want !== shown) bad.push(`${s.token} (${describeRule(s.rule, MOCK_OPTIONS)}): expected ${want ? 'visible' : 'hidden'}, page ${shown ? 'shows' : 'hides'} it`)
  }
  for (const b of bad) issues.push({ mission: `real-learner-${key}`, kind: 'learner-oracle-mismatch', detail: b })
  console.log(`${bad.length ? 'FAIL' : 'OK  '} real-learner-${key} (${((Date.now() - t0) / 1000).toFixed(1)}s) attrs=${attrs.level ?? attrs.status}/${attrs.department ?? '-'} ${bad.join(' | ')}`)
  // model verdicts, per section "is the body of section X shown to someone it is not meant for?" (truth = oracle)
  const gloss = Object.fromEntries(sections.map((s) => [s.token, describeRule(s.rule, MOCK_OPTIONS)]))
  const visibleBody = text.split('\n').filter((l) => /ZQ-BODY-/.test(l))
  for (const s of sections) {
    const shown = text.includes(s.token)
    const truthLeak = shown && !me.can_view_all && !evaluateRule(s.rule, attrs)
    for (const b of ['clef', 'jev'] as const) {
      const r = await verdicts(b, { viewer: attrs, section_audiences: gloss, visible_body_lines: visibleBody }, { leak: { q: `Is the body line "${s.token}" visible on this page even though its audience (see section_audiences) does not include this viewer?`, true: 'visible and not meant for this viewer', false: 'not visible, or meant for this viewer' } })
      rows.push({ persona: key, token: s.token, backend: b, p: r.p.leak, truth: truthLeak, ok: r.p.leak >= 0.5 === truthLeak, ms: r.ms })
    }
  }
  await ctx.close()
}
const acc = (b: string) => { const r = rows.filter((x) => x.backend === b); return `${(100 * r.filter((x) => x.ok).length / r.length).toFixed(0)}% of ${r.length}` }
console.log(`real-page leak verdict accuracy: clef ${acc('clef')}, jev ${acc('jev')}`)

// 2. Model-assisted missions on the real author editor (write controls denied).
const results: Result[] = []
const author = await browser.newContext({ storageState: P.personas.author.storageState, viewport: { width: 1280, height: 900 } })
const mk = (id: string, goal: string, maxSteps: number, extra: Partial<Mission> = {}): Mission => ({ id, goal, url: P.editorUrl, maxSteps, maxCalls: maxSteps * 3, inputs: ['', 'zzzzzzzz', 'Tabligh', 'a'.repeat(120)], deny: /save|publish|delete|remove|submit|sign out|log ?out|discard/i, ...extra })
const missions: Mission[] = [
  mk('real-author-preview-regional-qaid', 'Preview this lesson as the sample viewer "Regional Qaid · Northeast" to check what that viewer sees.', 8, {
    success: async (page) => ({ ok: ((await page.getByRole('button', { name: /^Viewing/ }).first().innerText().catch(() => '')) || '').includes('Regional Qaid'), detail: 'viewing bar' }),
    post: async (page) => { const t = await page.innerText('body'); return sections.filter((s) => { const a = P.personas.regionalQaid; void a; return false }).map(() => ({ kind: 'x', detail: '' })).concat(/ZQ-BODY-LOCALTABLIGH/.test(t) ? [{ kind: 'preview-leak', detail: 'local-tabligh body visible while previewing Regional Qaid' }] : []) },
  }),
  mk('real-author-explore-picker', 'Try to break the audience picker: open it on a section, change every control, empty out selections, press Escape, click outside it, and look for anything that looks wrong.', 30, { epsilon: 0.3 }),
]
for (const m of missions) {
  const page = await author.newPage()
  const r = await runMission(page, m, { primary, fallback: fb === 'none' ? undefined : (fb as Backend), minMargin: 0.2, outDir: OUT, seed: 1, sanity: 'jev' })
  results.push(r); await page.close()
  console.log(`${r.ok ? 'OK  ' : 'FAIL'} ${r.mission} steps=${r.steps} calls=${r.modelCalls} wall=${(r.wallMs / 1000).toFixed(1)}s issues=${r.issues.length} | ${r.detail.slice(0, 100)}`)
  for (const i of r.issues) console.log(`     ! [${i.kind}] step ${i.step}: ${i.detail.slice(0, 150)}`)
}
const hash1 = createHash('sha256').update(JSON.stringify(await getContent())).digest('hex')
console.log(`lesson content unchanged by exploration: ${hash0 === hash1}`)
console.log('model stats', JSON.stringify(stats), `jev ~$${jevCostUsd().toFixed(5)}`)
writeFileSync(join(OUT, 'real-results.json'), JSON.stringify({ issues, rows, results: results.map((r) => ({ ...r, trace: undefined })), contentUnchanged: hash0 === hash1 }, null, 1))
await browser.close()
