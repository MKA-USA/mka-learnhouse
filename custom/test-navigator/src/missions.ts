import type { Page } from 'playwright-core'
import { validateRule } from '../../../apps/web/components/mka/audience/evaluate'
import type { Mission } from './navigator'
import { PERSONAS, checkText } from './oracle'

export const BASE = process.env.TN_BASE ?? 'http://localhost:3517'
const EDITOR = `${BASE}/examples/mka-audience-editor`
const PLAYGROUND = `${BASE}/examples/mka-audience-playground`

const para = (t: string) => ({ type: 'paragraph', content: t ? [{ type: 'text', text: t }] : [] })
/** A lesson with no audience sections yet: what an author sees before using the feature. */
async function plainLesson(page: Page) {
  await page.waitForFunction(() => !!(window as unknown as { __editor?: unknown }).__editor, null, { timeout: 8000 })
  await page.evaluate((doc) => (window as unknown as { __editor: { commands: { setContent(d: unknown): void } } }).__editor.commands.setContent(doc), {
    type: 'doc',
    content: [
      { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'Monthly reporting' }] },
      para('Submit your monthly report by the 5th.'),
      para('Regional reviewers check the local reports.'),
      para(''),
    ],
  })
  await page.waitForTimeout(300)
}
const sections = (page: Page) =>
  page.evaluate(() => {
    const doc = (window as unknown as { __editor: { getJSON(): { content: Array<{ type: string; attrs?: { rule?: unknown } }> } } }).__editor.getJSON()
    return doc.content.filter((n) => n.type === 'mkaAudience').map((n) => n.attrs?.rule as { mode: string; groups: Array<Record<string, string[]>> })
  })

const authorBase: Mission = {
  id: 'author-create-local-tabligh-nazim',
  goal: 'In this lesson editor, make a section of the lesson that only Local Tabligh Nazims (local-level officeholders, Tabligh department, Nazim role) will see, and save it.',
  url: `${EDITOR}?mode=edit`,
  maxSteps: 40,
  maxCalls: 90,
  inputs: ['/', 'show', 'visible', 'who', 'hide', 'role'],
  setup: plainLesson,
  success: async (page) => {
    const rs = await sections(page)
    const r = rs.find((x) => x.mode === 'show' && x.groups[0]?.level?.length === 1 && x.groups[0].level[0] === 'local' && x.groups[0].department?.includes('tabligh'))
    const pickerOpen = (await page.getByRole('button', { name: 'Done' }).count()) > 0
    if (!r) return { ok: false, detail: `no matching section yet (${JSON.stringify(rs)})` }
    if (pickerOpen) return { ok: false, detail: 'rule matches but picker still open (not saved)' }
    const role = r.groups[0].role?.includes('nazim_dept')
    return { ok: true, detail: `rule ${JSON.stringify(r)}${role ? '' : ' (role Nazim not set)'}` }
  },
}

export const authorCreate: Mission = authorBase
/** Upper bound: the author already knows the word "audience" (e.g. read the guide). */
export const authorCreateHinted: Mission = { ...authorBase, id: 'author-create-hinted', inputs: ['/', 'audience', 'role', 'x'] }

/** Same, but the (currently broken, see FINDINGS F1) mouse path on the slash item is denied so the run must use the keyboard path. */
export const authorCreateHintedKbd: Mission = { ...authorBase, id: 'author-create-hinted-keyboard', inputs: ['/', 'audience', 'role', 'x'], deny: /^Audience section/ }

export const previewAs = (personaId: string): Mission => {
  const p = PERSONAS.find((x) => x.id === personaId)!
  return {
    id: `preview-as-${p.id}`,
    goal: `Preview this lesson as the sample viewer "${p.label}" so you can check what that viewer sees.`,
    url: `${EDITOR}?mode=edit`,
    maxSteps: 8,
    maxCalls: 20,
    inputs: [],
    success: async (page) => {
      const t = (await page.getByRole('button', { name: /^Viewing/ }).first().innerText().catch(() => '')).replace(/\s+/g, ' ')
      return { ok: t.includes(p.label) && !(await page.getByRole('menu').count()), detail: `bar: ${t}` }
    },
    post: async (page) => {
      const text = await page.innerText('body')
      return checkText(text, p).map((d) => ({ kind: 'preview-leak', detail: d }))
    },
  }
}

export const learnerView = (personaId: string): Mission => {
  const p = PERSONAS.find((x) => x.id === personaId)!
  return {
    id: `learner-${p.id}`,
    goal: `As the learner "${p.label}", read the lesson. Find any text meant for a different audience.`,
    url: `${EDITOR}?mode=view&mka_viewer=${p.id}`,
    maxSteps: 0,
    maxCalls: 0,
    inputs: [],
    post: async (page) => checkText(await page.innerText('body'), p).map((d) => ({ kind: 'learner-leak', detail: d })),
  }
}

const pickerInvariants: Mission['invariants'] = async (page, obs) => {
  const out: Array<{ kind: string; detail: string }> = []
  // 1. every authored rule in the document still validates (nothing the UI wrote is "damaged")
  if (page.url().includes('mka-audience-editor')) {
    const rs = await sections(page).catch(() => [])
    rs.forEach((r, i) => { const v = validateRule(r); if (!v.ok) out.push({ kind: 'invalid-rule', detail: `section ${i}: ${v.error} ${JSON.stringify(r)}` }) })
  }
  // 2. an open picker must fit the viewport (no clipped Done/Cancel)
  const done = page.getByRole('button', { name: 'Done' }).first()
  if (await done.count()) {
    const b = await done.boundingBox()
    const vp = page.viewportSize()!
    if (b && (b.x < 0 || b.x + b.width > vp.width + 1)) out.push({ kind: 'picker-clipped', detail: `Done button at ${JSON.stringify(b)} horizontally outside viewport ${vp.width}x${vp.height}` })
  }
  void obs
  return out
}

export const breakPicker = (variant: 'desktop' | 'phone' | 'keyboard'): Mission => ({
  id: `break-picker-${variant}`,
  goal: 'Try to break the audience picker: open it, change every control, empty out selections, press Escape, click outside it, use the keyboard, and look for anything that looks wrong or crashes.',
  url: `${EDITOR}?mode=edit`,
  viewport: variant === 'phone' ? { width: 375, height: 700 } : { width: 1280, height: 900 },
  maxSteps: 40,
  maxCalls: 90,
  inputs: ['', ' ', 'zzzzzzzz', '<script>alert(1)</script>', 'Tabligh', 'a'.repeat(300), '😀', "'; DROP TABLE x;--"],
  keys: variant === 'keyboard' ? ['Escape', 'Enter', 'Tab', 'ArrowDown', 'ArrowUp', ' '] : ['Escape', 'Enter', 'Tab'],
  epsilon: 0.3,
  invariants: pickerInvariants,
})

export const playgroundExplore = (phone: boolean): Mission => ({
  id: `playground-explore-${phone ? 'phone' : 'desktop'}`,
  goal: 'Explore this design playground of audience pickers and previews; try every control and look for anything broken.',
  url: PLAYGROUND,
  viewport: phone ? { width: 375, height: 700 } : { width: 1280, height: 900 },
  maxSteps: 40,
  maxCalls: 90,
  inputs: ['', 'zzzzzzzz', 'Tabligh', 'Albany', 'a'.repeat(200)],
  epsilon: 0.3,
  invariants: pickerInvariants,
})
