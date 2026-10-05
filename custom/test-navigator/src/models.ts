// Typed-decision backends. Both speak the TypeSafe System One request shape (`POST /v1/systemone`):
//   clef  = local Ollama `clef-flash:latest` (decision head, no network, free)
//   jev   = TypeSafe cloud `jev-latest` (TYPESAFE_API_KEY from env; never logged)
// The model only ever answers typed questions (choice / noul); deterministic code does everything else.
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'

export type Backend = 'clef' | 'jev'
export type Choice = { type: 'choice'; instructions: unknown; criteria: Record<string, unknown> }
export type Noul = { type: 'noul'; instructions: unknown; criteria?: { true?: string; false?: string } }
export type Question = Choice | Noul
export type ChoiceAnswer = { type: 'choice'; choice: string; probabilities: Record<string, number>; confidence: number }
export type NoulAnswer = { type: 'noul'; noul: number }
export type Answer = ChoiceAnswer | NoulAnswer

export type Stats = { calls: number; cached: number; inputTokens: number; ms: number }
export const stats: Record<Backend, Stats> = {
  clef: { calls: 0, cached: 0, inputTokens: 0, ms: 0 },
  jev: { calls: 0, cached: 0, inputTokens: 0, ms: 0 },
}
/** Jev list price: $0.042 / Mtok input, output free (docs.typesafe.ai/models). */
export const jevCostUsd = () => (stats.jev.inputTokens / 1e6) * 0.042

const URLS: Record<Backend, string> = {
  clef: process.env.TN_CLEF_URL ?? 'http://127.0.0.1:11434/v1/systemone',
  jev: 'https://api.typesafe.ai/v1/systemone',
}
const MODELS: Record<Backend, string> = { clef: 'clef-flash:latest', jev: 'jev-latest' }

let caching = true
export const setCaching = (on: boolean) => { caching = on }
let cachePath: string | undefined
let cache: Record<string, { answers: Record<string, Answer>; tokens: number }> = {}
export function useCache(path: string) {
  cachePath = path
  cache = existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) : {}
}
function persist() {
  if (!cachePath) return
  mkdirSync(dirname(cachePath), { recursive: true })
  writeFileSync(cachePath, JSON.stringify(cache))
}

function jevKey(): string {
  const k = process.env.TYPESAFE_API_KEY
  if (!k) throw new Error('TYPESAFE_API_KEY not set (Jev unavailable)')
  return k
}

export async function ask(
  backend: Backend,
  state: unknown,
  questions: Record<string, Question>,
): Promise<{ answers: Record<string, Answer>; ms: number; cached: boolean }> {
  const body = JSON.stringify({ model: MODELS[backend], state, questions })
  const key = createHash('sha256').update(backend + body).digest('hex')
  const s = stats[backend]
  if (caching && cache[key]) {
    s.cached++
    return { answers: cache[key].answers, ms: 0, cached: true }
  }
  const headers: Record<string, string> = { 'content-type': 'application/json' }
  if (backend === 'jev') headers.authorization = `Bearer ${jevKey()}`
  const t0 = performance.now()
  let res: Response | undefined
  for (let attempt = 0; attempt < 3; attempt++) {
    res = await fetch(URLS[backend], { method: 'POST', headers, body })
    if (res.status !== 429 && res.status < 500) break
    await new Promise((r) => setTimeout(r, 500 * 2 ** attempt))
  }
  const ms = performance.now() - t0
  if (!res || !res.ok) throw new Error(`${backend} ${res?.status}: ${(await res?.text())?.slice(0, 200)}`)
  const json = (await res.json()) as { answers: Record<string, Answer>; usage?: { input_tokens?: number } }
  const tokens = json.usage?.input_tokens ?? 0
  s.calls++
  s.ms += ms
  s.inputTokens += tokens
  cache[key] = { answers: json.answers, tokens }
  persist()
  return { answers: json.answers, ms, cached: false }
}

/** Convenience: one choice question. */
export async function choose(backend: Backend, state: unknown, instructions: unknown, criteria: Record<string, unknown>) {
  const r = await ask(backend, state, { q: { type: 'choice', instructions, criteria } })
  const a = r.answers.q as ChoiceAnswer
  const sorted = Object.values(a.probabilities).sort((x, y) => y - x)
  return { choice: a.choice, confidence: a.confidence, p: sorted[0] ?? 0, margin: (sorted[0] ?? 0) - (sorted[1] ?? 0), ms: r.ms, cached: r.cached, probabilities: a.probabilities }
}

/** Convenience: several noul verdicts over the same state in one request (parallel server-side). */
export async function verdicts(backend: Backend, state: unknown, qs: Record<string, { q: string; true?: string; false?: string }>) {
  const questions: Record<string, Question> = {}
  for (const [id, v] of Object.entries(qs)) questions[id] = { type: 'noul', instructions: v.q, criteria: v.true || v.false ? { true: v.true, false: v.false } : undefined }
  const r = await ask(backend, state, questions)
  const out: Record<string, number> = {}
  for (const id of Object.keys(qs)) out[id] = (r.answers[id] as NoulAnswer).noul
  return { p: out, ms: r.ms, cached: r.cached }
}

/** Screenshot verdict, clef only: Ollama's decision endpoint accepts top-level `images` (base64); Jev rejects images (400). */
export async function verdictImage(png: Buffer, question: string): Promise<{ p: number; ms: number }> {
  const t0 = performance.now()
  const res = await fetch(URLS.clef, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ model: MODELS.clef, state: 'screenshot of a web page', images: [png.toString('base64')], questions: { q: { type: 'noul', instructions: question } } }) })
  if (!res.ok) throw new Error(`clef image ${res.status}`)
  const json = (await res.json()) as { answers: { q: NoulAnswer } }
  stats.clef.calls++
  return { p: json.answers.q.noul, ms: performance.now() - t0 }
}
