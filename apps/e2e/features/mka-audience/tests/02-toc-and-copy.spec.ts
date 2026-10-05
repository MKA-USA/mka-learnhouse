import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SECTIONS, UNTARGETED, HIDDEN_FOR } from '../fixture'
import { PERSONAS } from '../personas'
import { markers, openLesson, stackAvailable } from '../helpers'

test.skip(!stackAvailable(), 'MKA e2e stack is not running (apps/e2e/mka/stack.sh up)')

const learners = PERSONAS.filter((p) => p.key !== 'author')

const tocTexts = (page: Page) => page.locator('.toc-item').allInnerTexts()

for (const p of learners) {
  test(`${p.label}: table of contents lists the untargeted and its own headings`, async ({ browser }) => {
    const { ctx, page } = await openLesson(browser, p.key)
    try {
      const toc = (await tocTexts(page)).map((t) => t.trim())
      expect(toc).toContain(UNTARGETED.heading)
      for (const k of p.visible) expect(toc).toContain(SECTIONS[k].heading)
    } finally {
      await ctx.close()
    }
  })

  // FINDING-1 (FINDINGS.md): the learner's table of contents lists the headings of sections hidden from them.
  test(`${p.label}: table of contents does not list hidden headings`, async ({ browser }) => {
    test.fail(true, 'FINDING-1: TOC leaks hidden section headings (see FINDINGS.md)')
    const { ctx, page } = await openLesson(browser, p.key)
    try {
      const toc = (await tocTexts(page)).join('\n')
      for (const k of HIDDEN_FOR(p.visible)) expect(toc).not.toContain(SECTIONS[k].heading)
    } finally {
      await ctx.close()
    }
  })

  // FINDING-3 (FINDINGS.md): select-all + copy serializes the WHOLE lesson, hidden sections included (the editor state is
  // never filtered for the learner). The DOM selection itself is clean; the clipboard payload is not.
  test(`${p.label}: select-all + copy contains no hidden text`, async ({ browser }) => {
    test.fail(HIDDEN_FOR(p.visible).length > 0, 'FINDING-3: copied text includes hidden sections (see FINDINGS.md)')
    const { ctx, page } = await openLesson(browser, p.key)
    try {
      await page.evaluate(() => {
        ;(window as any).__copied = null
        document.addEventListener('copy', (e) => {
          ;(window as any).__copied = { text: e.clipboardData?.getData('text/plain') ?? '', html: e.clipboardData?.getData('text/html') ?? '' }
        })
      })
      await page.locator('.ProseMirror').first().click({ position: { x: 4, y: 4 } })
      await page.keyboard.press('ControlOrMeta+A')
      await page.keyboard.press('ControlOrMeta+C')
      const copied = await page.evaluate(() => (window as any).__copied as { text: string; html: string } | null)
      expect(copied, 'no copy event fired').not.toBeNull()
      const selection = await page.evaluate(() => window.getSelection()?.toString() ?? '')
      const hidden = markers(HIDDEN_FOR(p.visible))
      for (const m of hidden) {
        expect(copied!.text, `hidden "${m}" in copied text/plain`).not.toContain(m)
        expect(copied!.html, `hidden "${m}" in copied text/html`).not.toContain(m)
        expect(selection, `hidden "${m}" in the DOM selection`).not.toContain(m)
      }
    } finally {
      await ctx.close()
    }
  })

  test(`${p.label}: select-all + copy contains the sections the learner can see`, async ({ browser }) => {
    const { ctx, page } = await openLesson(browser, p.key)
    try {
      await page.evaluate(() => {
        ;(window as any).__copied = null
        document.addEventListener('copy', (e) => {
          ;(window as any).__copied = { text: e.clipboardData?.getData('text/plain') ?? '' }
        })
      })
      await page.locator('.ProseMirror').first().click({ position: { x: 4, y: 4 } })
      await page.keyboard.press('ControlOrMeta+A')
      await page.keyboard.press('ControlOrMeta+C')
      const copied = await page.evaluate(() => (window as any).__copied as { text: string } | null)
      expect(copied).not.toBeNull()
      expect(copied!.text).toContain(UNTARGETED.body)
      for (const m of markers(p.visible)) expect(copied!.text, `visible "${m}" missing from copied text`).toContain(m)
    } finally {
      await ctx.close()
    }
  })
}
