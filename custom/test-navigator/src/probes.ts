// Deterministic probes (no model). Each one is a scripted repro of a "try to break the picker" idea; failures are
// candidate findings, and re-running a probe is the "replay without the model" check.
// Usage: bun run src/probes.ts [probe-id ...] [--runs 3]
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Browser, Page } from 'playwright-core'
import { launch, newPage } from './browser'
import { BASE } from './missions'

const EDITOR = `${BASE}/examples/mka-audience-editor`
const OUT = join(import.meta.dir, '../../../docs/screens/audience/explore/probes')
type R = { id: string; ok: boolean; expected: string; actual: string; shot?: string }
type Probe = { id: string; title: string; kind?: 'bug' | 'ux' | 'quirk'; run: (page: Page, b: Browser) => Promise<Omit<R, 'id'>>; viewport?: { width: number; height: number } }

const ed = (page: Page) => page.waitForFunction(() => !!(window as any).__editor, null, { timeout: 8000 })
const openEditor = async (page: Page, q = 'mode=edit') => { await page.goto(`${EDITOR}?${q}`, { waitUntil: 'networkidle' }); await ed(page); await page.waitForTimeout(700) }
const rules = (page: Page) => page.evaluate(() => (window as any).__editor.getJSON().content.filter((n: any) => n.type === 'mkaAudience').map((n: any) => n.attrs.rule))
const pickerOpen = async (page: Page) => (await page.getByRole('button', { name: 'Done' }).count()) > 0
const openPicker = async (page: Page, nth = 0) => { await page.getByRole('button', { name: 'Edit' }).nth(nth).click(); await page.waitForTimeout(450) }
const active = (page: Page) => page.evaluate(() => { const a = document.activeElement as HTMLElement; return `${a.tagName}${a.getAttribute('aria-label') ? `[${a.getAttribute('aria-label')}]` : ''} "${(a.innerText || '').replace(/\s+/g, ' ').slice(0, 30)}"` })
const shot = async (page: Page, id: string) => { mkdirSync(OUT, { recursive: true }); const f = `${id}.png`; await page.screenshot({ path: join(OUT, f) }); return `probes/${f}` }
const setDoc = (page: Page, content: unknown[]) => page.evaluate((c) => (window as any).__editor.commands.setContent({ type: 'doc', content: c }), content)
const sec = (rule: unknown, text: string, id: string) => ({ type: 'mkaAudience', attrs: { id, rule }, content: [{ type: 'paragraph', content: [{ type: 'text', text }] }] })

export const probes: Probe[] = [
  {
    id: 'slash-click-audience-section',
    title: 'Mouse-selecting "Audience section" in the slash menu creates a section',
    run: async (page) => {
      await openEditor(page)
      await setDoc(page, [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }, { type: 'paragraph' }])
      const bb = (await page.locator('.ProseMirror').boundingBox())!
      await page.mouse.click(bb.x + 24, bb.y + bb.height - 10)
      await page.keyboard.type('/audience', { delay: 20 })
      await page.getByRole('button', { name: /Audience section/ }).click()
      await page.waitForTimeout(700)
      const n = (await rules(page)).length
      return { ok: n === 1 && (await pickerOpen(page)), expected: 'one audience section exists and the picker opens (same as pressing Enter)', actual: `${n} sections, picker open=${await pickerOpen(page)}`, shot: await shot(page, 'slash-click-audience-section') }
    },
  },
  {
    id: 'slash-enter-audience-section',
    title: 'Keyboard Enter on "Audience section" in the slash menu creates a section (control for the click probe)',
    run: async (page) => {
      await openEditor(page)
      await setDoc(page, [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }, { type: 'paragraph' }])
      const bb = (await page.locator('.ProseMirror').boundingBox())!
      await page.mouse.click(bb.x + 24, bb.y + bb.height - 10)
      await page.keyboard.type('/audience', { delay: 20 })
      await page.keyboard.press('Enter'); await page.waitForTimeout(600)
      const n = (await rules(page)).length
      return { ok: n === 1 && (await pickerOpen(page)), expected: 'one section and picker open', actual: `${n} sections, picker open=${await pickerOpen(page)}` }
    },
  },
  {
    id: 'shortcut-audience-section',
    title: 'Cmd/Ctrl+Alt+A wraps the selected paragraph in a section',
    run: async (page) => {
      await openEditor(page)
      await setDoc(page, [{ type: 'paragraph', content: [{ type: 'text', text: 'Wrap me' }] }, { type: 'paragraph', content: [{ type: 'text', text: 'Other' }] }])
      await page.locator('.ProseMirror p').first().click({ clickCount: 3 })
      await page.keyboard.press('ControlOrMeta+Alt+a'); await page.waitForTimeout(600)
      const n = (await rules(page)).length
      return { ok: n === 1, expected: 'one section wrapping the paragraph', actual: `${n} sections` }
    },
  },
  {
    id: 'escape-reverts-and-closes',
    title: 'Escape closes the picker and discards unsaved changes',
    run: async (page) => {
      await openEditor(page); const before = JSON.stringify(await rules(page))
      await openPicker(page); await page.getByRole('button', { name: 'Regional', exact: true }).click(); await page.keyboard.press('Escape'); await page.waitForTimeout(300)
      const after = JSON.stringify(await rules(page))
      return { ok: !(await pickerOpen(page)) && before === after, expected: 'picker closed, rules unchanged', actual: `open=${await pickerOpen(page)} unchanged=${before === after}`, shot: await shot(page, 'escape-reverts-and-closes') }
    },
  },
  {
    id: 'cancel-reverts',
    title: 'Cancel discards unsaved changes',
    run: async (page) => {
      await openEditor(page); const before = JSON.stringify(await rules(page))
      await openPicker(page); await page.getByRole('button', { name: 'Regional', exact: true }).click(); await page.getByRole('button', { name: 'Cancel' }).click(); await page.waitForTimeout(300)
      return { ok: before === JSON.stringify(await rules(page)), expected: 'rules unchanged', actual: JSON.stringify(await rules(page)) }
    },
  },
  {
    id: 'focus-returns-after-close',
    kind: 'ux',
    title: 'Keyboard focus returns to the opener (Edit) after the picker closes',
    run: async (page) => {
      await openEditor(page)
      const res: string[] = []
      for (const how of ['Escape', 'Cancel', 'Done']) {
        await page.getByRole('button', { name: 'Edit' }).first().focus(); await page.keyboard.press('Enter'); await page.waitForTimeout(450)
        if (how === 'Escape') await page.keyboard.press('Escape'); else await page.getByRole('button', { name: how, exact: true }).click()
        await page.waitForTimeout(300)
        res.push(`${how}: ${await active(page)}`)
      }
      const ok = res.filter((r) => !r.startsWith('Done')).every((r) => /Edit|ProseMirror|PUBLIC intro/.test(r))
      return { ok, expected: 'after Escape and after Cancel focus lands back on the opener (Edit) or inside the editor, not on <body>', actual: res.join(' | '), shot: await shot(page, 'focus-returns-after-close') }
    },
  },
  {
    id: 'focus-trap-in-picker',
    title: 'While the picker is open, Tab stays inside it (or it is non-modal by design)',
    run: async (page) => {
      await openEditor(page); await openPicker(page)
      const seen: string[] = []
      let escaped = 0
      for (let i = 0; i < 24; i++) {
        await page.keyboard.press('Tab')
        const inside = await page.evaluate(() => { const a = document.activeElement; return !!a?.closest('[role=dialog]') })
        if (!inside) { escaped++; seen.push(await active(page)) }
      }
      return { ok: escaped === 0, expected: 'focus never leaves the open picker in 24 Tab presses', actual: `focus left the picker ${escaped} times; e.g. ${seen.slice(0, 3).join(' ; ')}`, shot: await shot(page, 'focus-trap-in-picker') }
    },
  },
  {
    id: 'escape-nested-popover',
    title: 'Escape inside the department popover closes only the popover, not the whole picker',
    run: async (page) => {
      await openEditor(page); await openPicker(page)
      await page.getByRole('button', { name: /Department/ }).click(); await page.waitForTimeout(300)
      await page.keyboard.press('Escape'); await page.waitForTimeout(300)
      return { ok: await pickerOpen(page), expected: 'picker still open after first Escape', actual: `picker open=${await pickerOpen(page)}`, shot: await shot(page, 'escape-nested-popover') }
    },
  },
  {
    id: 'empty-hide-warning',
    kind: 'ux',
    title: 'Hide-from with no filters (hides from every officeholder) warns the author',
    run: async (page) => {
      await openEditor(page); await openPicker(page)
      await page.getByRole('button', { name: 'Local', exact: true }).click() // clear Local
      await page.getByText('Hide from', { exact: true }).click(); await page.waitForTimeout(300)
      const body = (await page.locator('[role=dialog]').last().innerText()).replace(/\s+/g, ' ')
      return { ok: /Only people who aren't officeholders will see this\./.test(body), expected: 'the note "Only people who aren\'t officeholders will see this."', actual: body.slice(0, 300), shot: await shot(page, 'empty-hide-warning') }
    },
  },
  {
    id: 'unknown-and-damaged-rules',
    title: 'Unknown rule values and damaged rules do not crash the editor; learners fail safe',
    run: async (page) => {
      await openEditor(page)
      await setDoc(page, [
        sec({ v: 1, mode: 'show', groups: [{ level: ['galactic'], department: ['zzz'] }] }, 'UNKNOWN-VALUES body', 'u1'),
        sec({ v: 7, mode: 'show', groups: [{ level: ['local'] }] }, 'FUTURE-VERSION body', 'u2'),
        sec({ v: 1, mode: 'bogus', groups: [] }, 'DAMAGED body', 'u3'),
        sec(null, 'NULL-RULE body', 'u4'),
        { type: 'paragraph', content: [{ type: 'text', text: 'tail' }] },
      ])
      await page.waitForTimeout(500)
      const text = (await page.innerText('body')).replace(/\s+/g, ' ')
      await openPicker(page, 0).catch(() => {}); const opened = await pickerOpen(page); await page.keyboard.press('Escape')
      const crashed = /Application error|Unhandled Runtime Error/.test(text) || text.length < 40
      // learner view of the same content is checked separately in the view page; here: author must see all bodies + some "damaged" cue
      const cue = /damaged|unknown|invalid/i.test(text)
      return { ok: !crashed && cue && opened, expected: 'no crash; damaged/unknown rules are labelled for the author; picker opens on an unknown-valued rule', actual: `crashed=${crashed} cue=${cue} pickerOpensOnUnknown=${opened} text="${text.slice(0, 200)}"`, shot: await shot(page, 'unknown-and-damaged-rules') }
    },
  },
  {
    id: 'phone-picker-sheet',
    title: 'On a 375x667 phone (iPhone SE size) the picker footer (Cancel/Done) is visible without scrolling',
    viewport: { width: 375, height: 667 },
    run: async (page) => {
      await openEditor(page); await openPicker(page)
      const m = await page.evaluate(() => {
        const dlg = document.querySelector('[role=dialog]:last-of-type') ?? document.querySelector('[role=dialog]')
        const small = Array.from((dlg ?? document).querySelectorAll('button,[role=checkbox],[role=switch],a')).map((e) => { const r = e.getBoundingClientRect(); return { n: (e.getAttribute('aria-label') || (e as HTMLElement).innerText || '').replace(/\s+/g, ' ').slice(0, 28), w: Math.round(r.width), h: Math.round(r.height) } }).filter((x) => x.h > 0 && (x.h < 40 || x.w < 40))
        return { sw: document.documentElement.scrollWidth, iw: innerWidth, small }
      })
      const done = (await page.getByRole('button', { name: 'Done' }).boundingBox())!
      const inView = done.y + done.height <= 667 && done.x + done.width <= 375
      const ok = m.sw <= m.iw + 1 && inView && m.small.length === 0
      return { ok, expected: 'no h-scroll, Done fully inside the 375x667 viewport, every control >= 40x40', actual: `scrollWidth=${m.sw}/${m.iw} doneBox=${JSON.stringify(done)} doneInView=${inView} smallTargets=${JSON.stringify(m.small).slice(0, 300)}`, shot: await shot(page, 'phone-picker-sheet') }
    },
  },
  {
    id: 'phone-editor-page',
    title: 'At 375px the editor page (section headers, Viewing bar) has no horizontal overflow',
    viewport: { width: 375, height: 700 },
    run: async (page) => {
      await openEditor(page)
      const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: innerWidth }))
      return { ok: m.sw <= m.iw + 1, expected: 'scrollWidth <= 375', actual: `scrollWidth=${m.sw}`, shot: await shot(page, 'phone-editor-page') }
    },
  },
  {
    id: 'xss-in-department-search',
    title: 'HTML typed into the department search renders as text, never executes',
    run: async (page) => {
      await openEditor(page); await openPicker(page)
      await page.getByRole('button', { name: /Department/ }).click(); await page.waitForTimeout(300)
      const box = page.getByRole('combobox').or(page.getByRole('searchbox')).or(page.locator('input[type=text],input:not([type])')).first()
      await box.fill('<img src=x onerror="window.__xss=1">'); await page.waitForTimeout(400)
      const x = await page.evaluate(() => (window as any).__xss)
      return { ok: x === undefined, expected: 'no script execution', actual: `window.__xss=${x}`, shot: await shot(page, 'xss-in-department-search') }
    },
  },
  {
    id: 'unknown-viewer-id-fails-closed',
    kind: 'quirk',
    title: '?mka_viewer=<unknown id> does not silently show the first persona content (mock layer)',
    run: async (page) => {
      await page.goto(`${EDITOR}?mode=view&mka_viewer=does-not-exist`, { waitUntil: 'networkidle' }); await page.waitForTimeout(800)
      const t = await page.innerText('body')
      return { ok: !t.includes('LOCAL-ONLY:'), expected: 'unknown id => unrecognized viewer (no LOCAL-ONLY section)', actual: `LOCAL-ONLY visible=${t.includes('LOCAL-ONLY:')}`, shot: await shot(page, 'unknown-viewer-id-fails-closed') }
    },
  },

  {
    id: 'pointerdown-in-editor-cancels-new',
    title: 'New section (slash + Enter): clicking into the editor text cancels it (section removed, picker closed)',
    run: async (page) => {
      await openEditor(page)
      await setDoc(page, [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }, { type: 'paragraph' }])
      const bb = (await page.locator('.ProseMirror').boundingBox())!
      await page.mouse.click(bb.x + 24, bb.y + bb.height - 10)
      await page.keyboard.type('/audience', { delay: 20 }); await page.keyboard.press('Enter'); await page.waitForTimeout(500)
      const openBefore = await pickerOpen(page)
      await page.locator('.ProseMirror p').first().click(); await page.waitForTimeout(500)
      const n = (await rules(page)).length
      return { ok: openBefore && n === 0 && !(await pickerOpen(page)), expected: 'picker open after Enter; after clicking editor text: 0 sections, picker closed', actual: `openBefore=${openBefore} sections=${n} openAfter=${await pickerOpen(page)}` }
    },
  },
  {
    id: 'pointerdown-in-editor-reverts-existing',
    title: 'Existing section: change a chip, click into the editor -> rule reverted and picker closed',
    run: async (page) => {
      await openEditor(page); const before = JSON.stringify(await rules(page))
      await openPicker(page); await page.getByRole('button', { name: 'Regional', exact: true }).click()
      await page.locator('.ProseMirror p').first().click(); await page.waitForTimeout(500)
      const after = JSON.stringify(await rules(page))
      return { ok: before === after && !(await pickerOpen(page)), expected: 'rules unchanged, picker closed', actual: `unchanged=${before === after} open=${await pickerOpen(page)} rules=${after.slice(0, 160)}` }
    },
  },
  {
    id: 'slash-click-then-done',
    title: 'Mouse slash insert -> pick Local -> Done keeps the section with the rule',
    run: async (page) => {
      await openEditor(page)
      await setDoc(page, [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }, { type: 'paragraph' }])
      const bb = (await page.locator('.ProseMirror').boundingBox())!
      await page.mouse.click(bb.x + 24, bb.y + bb.height - 10)
      await page.keyboard.type('/audience', { delay: 20 })
      await page.getByRole('button', { name: /Audience section/ }).click(); await page.waitForTimeout(600)
      await page.getByRole('button', { name: 'Local', exact: true }).click()
      await page.getByRole('button', { name: 'Done', exact: true }).click(); await page.waitForTimeout(500)
      const rs = await rules(page)
      const ok = rs.length === 1 && rs[0].groups?.[0]?.level?.[0] === 'local' && !(await pickerOpen(page))
      return { ok, expected: 'one section, level local, picker closed', actual: `rules=${JSON.stringify(rs)} open=${await pickerOpen(page)}` }
    },
  },
  {
    id: 'rapid-open-close',
    title: 'Rapidly toggling the picker / double-clicking Done leaves exactly one consistent state, no errors',
    run: async (page) => {
      const errs: string[] = []; page.on('pageerror', (e) => errs.push(e.message))
      await openEditor(page)
      for (let i = 0; i < 6; i++) { await page.getByRole('button', { name: 'Edit' }).first().click({ force: true }).catch(() => {}); await page.keyboard.press('Escape') }
      await openPicker(page); await page.getByRole('button', { name: 'Done' }).dblclick().catch(() => {}); await page.waitForTimeout(400)
      return { ok: errs.length === 0 && !(await pickerOpen(page)), expected: 'no page errors, picker closed', actual: `errors=${JSON.stringify(errs)} open=${await pickerOpen(page)}` }
    },
  },
]

if (import.meta.main) {
  const argv = process.argv.slice(2)
  const runs = Number(argv[argv.indexOf('--runs') + 1] || 1)
  const want = argv.filter((a, i) => !a.startsWith('--') && argv[i - 1] !== '--runs')
  const browser = await launch()
  const summary: Array<R & { passes: number; runs: number }> = []
  for (const p of probes.filter((x) => !want.length || want.includes(x.id))) {
    let last: R | undefined; let passes = 0
    for (let i = 0; i < runs; i++) {
      const { ctx, page } = await newPage(browser, p.viewport)
      try { last = { id: p.id, ...(await p.run(page, browser)) } } catch (e) { last = { id: p.id, ok: false, expected: 'probe completes', actual: `probe threw: ${(e as Error).message.split('\n')[0]}` } } finally { await ctx.close() }
      if (last.ok) passes++
    }
    summary.push({ ...(last as R), kind: p.kind ?? 'bug', title: p.title, passes, runs } as never)
    console.log(`${last!.ok ? 'PASS' : 'FAIL'} ${p.id} (${passes}/${runs})\n     expected: ${last!.expected}\n     actual:   ${last!.actual.slice(0, 400)}`)
  }
  await browser.close()
  writeFileSync(join(OUT, 'probe-results.json'), JSON.stringify(summary, null, 1))
}
