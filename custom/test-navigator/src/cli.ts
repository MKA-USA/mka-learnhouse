// Usage: bun run src/cli.ts <mission|group>... [--primary clef|jev] [--fallback jev|none] [--min-margin 0.2] [--seed 1] [--out dir]
// Groups: author | preview | learner | picker | playground | all
import { join } from 'node:path'
import { launch, newPage } from './browser'
import { authorCreate, authorCreateHinted, authorCreateHintedKbd, breakPicker, learnerView, playgroundExplore, previewAs } from './missions'
import { jevCostUsd, stats, useCache, type Backend } from './models'
import type { Mission, Result } from './navigator'
import { runMission } from './navigator'
import { PERSONAS } from './oracle'

const argv = process.argv.slice(2)
const flag = (n: string, d: string) => { const i = argv.indexOf(`--${n}`); return i >= 0 ? argv[i + 1] : d }
const names = argv.filter((a, i) => !a.startsWith('--') && !argv[i - 1]?.startsWith('--'))
const primary = flag('primary', 'clef') as Backend
const fb = flag('fallback', 'jev')
const outDir = flag('out', join(import.meta.dir, '../../../docs/screens/audience/explore'))
const seed = Number(flag('seed', '1'))
const idSuffix = flag('suffix', '')

const all: Record<string, () => Mission[]> = {
  author: () => [authorCreate],
  authorhint: () => [authorCreateHinted],
  authorkbd: () => [authorCreateHintedKbd],
  preview: () => PERSONAS.map((p) => previewAs(p.id)),
  learner: () => PERSONAS.map((p) => learnerView(p.id)),
  picker: () => [breakPicker('desktop'), breakPicker('phone'), breakPicker('keyboard')],
  playground: () => [playgroundExplore(false), playgroundExplore(true)],
}
all.all = () => Object.values(all).flatMap((f) => f())
const missions = (names.length ? names : ['all']).flatMap((n) => (all[n] ? all[n]() : all.all().filter((m) => m.id === n)))

useCache(join(outDir, '.decision-cache.json'))
const browser = await launch()
const results: Result[] = []
for (const m of missions) {
  const { ctx, page } = await newPage(browser)
  try {
    const r = await runMission(page, m, { primary, fallback: fb === 'none' ? undefined : (fb as Backend), minMargin: Number(flag('min-margin', '0.2')), outDir, seed, sanity: flag('sanity', 'jev') === 'none' ? undefined : (flag('sanity', 'jev') as Backend) })
    results.push(r)
    console.log(`${r.ok ? 'OK  ' : 'FAIL'} ${r.mission} steps=${r.steps} calls=${r.modelCalls} wall=${(r.wallMs / 1000).toFixed(1)}s model=${(r.modelMs / 1000).toFixed(1)}s stop=${r.stoppedBy} issues=${r.issues.length} | ${r.detail.slice(0, 140)}`)
    for (const i of r.issues.slice(0, 6)) console.log(`     ! [${i.kind}] step ${i.step}: ${i.detail.slice(0, 160)}`)
  } finally { await ctx.close() }
}
await browser.close()
console.log('model stats', JSON.stringify(stats), `jev cost ~$${jevCostUsd().toFixed(5)}`)
