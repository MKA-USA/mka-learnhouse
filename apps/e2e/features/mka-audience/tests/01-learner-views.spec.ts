import { test, expect } from '@playwright/test'
import { SECTIONS, UNTARGETED } from '../fixture'
import { HIDDEN_FOR } from '../fixture'
import { PERSONAS } from '../personas'
import { editorText, markers, openLesson, pageHtmlWithoutToc, screenshot, stackAvailable } from '../helpers'

test.skip(!stackAvailable(), 'MKA e2e stack is not running (apps/e2e/mka/stack.sh up)')

// One load per persona: exact visible set, hidden markers absent, notes, inline fields.
for (const [i, p] of PERSONAS.entries()) {
  if (p.key === 'author') continue // sees everything: covered in 05
  test(`${p.label}: sees exactly its sections, hidden ones are not in the DOM`, async ({ browser }) => {
    const { ctx, page } = await openLesson(browser, p.key)
    try {
      const body = editorText(page)
      // untargeted content is always there
      await expect(body).toContainText(UNTARGETED.heading)
      await expect(body).toContainText(UNTARGETED.body)

      // exactly the expected sections are visible
      for (const key of p.visible) {
        await expect(body).toContainText(SECTIONS[key].heading)
        await expect(body).toContainText(SECTIONS[key].body)
      }
      const hidden = HIDDEN_FOR(p.visible)
      for (const key of hidden) {
        await expect(body).not.toContainText(SECTIONS[key].heading)
        await expect(body).not.toContainText(SECTIONS[key].body)
        await expect(page.getByText(SECTIONS[key].body)).toHaveCount(0)
      }

      // hidden text is not in the serialized page (the TOC is checked in 02)
      const html = await pageHtmlWithoutToc(page)
      for (const m of markers(hidden)) expect(html, `hidden marker "${m}" found in page.content()`).not.toContain(m)
      for (const m of markers(p.visible)) expect(html, `visible marker "${m}" missing from page.content()`).toContain(m)
      // hidden BODY markers must not appear anywhere in page.content(), TOC included
      const full = await page.content()
      for (const key of hidden) expect(full).not.toContain(SECTIONS[key].body)

      // the "tailored by role" note must never appear for a recognized account (the positive case is its own test below),
      // and the empty-lesson note never (untargeted content exists)
      if (!p.unrecognizedNote) await expect(page.getByTestId('mka-note-unrecognized')).toHaveCount(0)
      await expect(page.getByTestId('mka-note-empty')).toHaveCount(0)

      // inline fields show this persona's Majlis / Region (or the node's fallback text)
      const fields = page.locator('.ProseMirror p', { hasText: 'FIELDS Majlis:' })
      await expect(fields).toHaveText(`FIELDS Majlis: ${p.majlis ?? 'your Majlis'} Region: ${p.region ?? 'your region'} END`)

      // no author chrome for learners
      await expect(page.getByText('Visible to:')).toHaveCount(0)
      await expect(page.getByRole('region', { name: 'Audience preview' })).toHaveCount(0)

      await screenshot(page, `${String(i + 1).padStart(2, '0')}-${p.key}-learner`)
    } finally {
      await ctx.close()
    }
  })
}

// FINDING-2 (fixed; see docs/screens/audience/e2e/FINDINGS.md): learner note for an unrecognized account.
test('Unrecognized account: sees the "tailored by role" note', async ({ browser }) => {
  const { ctx, page } = await openLesson(browser, 'unrecognized')
  try {
    const note = page.getByTestId('mka-note-unrecognized')
    await expect(note).toBeVisible({ timeout: 5_000 })
    await expect(note).toContainText('Parts of this lesson are tailored by role')
  } finally {
    await ctx.close()
  }
})
