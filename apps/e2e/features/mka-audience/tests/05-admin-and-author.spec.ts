import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SECTIONS, UNTARGETED, HIDDEN_FOR } from '../fixture'
import { PERSONAS } from '../personas'
import type { PersonaKey, SectionKey } from '../personas'
import { SECTION_KEYS } from '../personas'
import { audienceBar, editorText, openEditor, openLesson, screenshot, seeded, stackAvailable } from '../helpers'

test.skip(!stackAvailable(), 'MKA e2e stack is not running (apps/e2e/mka/stack.sh up)')

const VIEWERS: { key: PersonaKey; name: string }[] = [
  { key: 'admin', name: 'org admin' },
  { key: 'author', name: 'course author' },
]

/** Preview-as personas offered by /options, with what each must see (same table as the real learner accounts). */
const PREVIEW_PERSONAS: { label: string; visible: SectionKey[]; majlis: string | null; region: string | null; note: boolean }[] = [
  ...PERSONAS.filter((p) => p.key !== 'author').map((p) => ({
    label: p.key === 'notOfficeholder' ? 'Not an officeholder' : p.label,
    visible: p.visible,
    majlis: p.majlis,
    region: p.region,
    note: p.unrecognizedNote,
  })),
  { label: 'Local Qaid · Houston', visible: ['hideNational'], majlis: 'Houston', region: 'Gulf', note: false },
]

async function chooseView(page: Page, label: string) {
  await audienceBar(page).getByRole('button', { name: /Viewing:/ }).click()
  await page.getByRole('button', { name: new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}( |$)`) }).click()
  await expect(audienceBar(page).getByRole('button', { name: /Viewing:/ })).toContainText(label)
}

for (const v of VIEWERS) {
  test.describe(`${v.name}`, () => {
    test(`sees every section with "Visible to" badges on the learner page`, async ({ browser }) => {
      const { ctx, page } = await openLesson(browser, v.key)
      try {
        const body = editorText(page)
        for (const k of SECTION_KEYS) {
          await expect(body).toContainText(SECTIONS[k].heading)
          await expect(body).toContainText(SECTIONS[k].body)
        }
        await expect(body).toContainText(UNTARGETED.body)
        // the Audience bar mounts on the LEARNER page every time (FINDING-0 fixed)
        await expect(audienceBar(page)).toContainText('Everything (author view)')
        await expect(audienceBar(page)).toContainText('5 audience sections')
        await expect(page.getByTestId('mka-field-chip')).toHaveCount(2)
        await expect(page.getByTestId('mka-counterparts-sample')).toBeVisible()
        // read-only badges, one per section
        await expect(page.getByText('Visible to:', { exact: true })).toHaveCount(4)
        await expect(page.getByText('Hidden from:', { exact: true })).toHaveCount(1)
        for (const label of ['Local officeholders in Tabligh', 'Regional Qaids', 'National officeholders', 'Officeholders in Albany']) {
          await expect(page.getByTitle(label, { exact: true })).toBeVisible()
        }
        // no learner notes for someone who sees everything
        await expect(page.getByTestId('mka-note-unrecognized')).toHaveCount(0)
        await expect(page.getByTestId('mka-note-empty')).toHaveCount(0)
        await screenshot(page, `10-${v.key}-everything`)
      } finally {
        await ctx.close()
      }
    })

    // FINDING-4 (FINDINGS.md): the read-only badge for a "Hide from" section reads "Hidden from: Everyone except national
    // officeholders", i.e. the opposite of the rule (the author header strips "Everyone except"; the badge does not).
    test(`"Hide from National" badge reads "Hidden from: National officeholders"`, async ({ browser }) => {
      const { ctx, page } = await openLesson(browser, v.key)
      try {
        await expect(page.getByText(/Hidden from:\s*Everyone except/)).toHaveCount(0, { timeout: 3_000 })
      } finally {
        await ctx.close()
      }
    })

    for (const route of ['editor', 'learner'] as const) test(`${route} page: can switch Preview-as personas and sees exactly what each persona sees`, async ({ browser }, testInfo) => {
      testInfo.setTimeout(120_000)
      const { ctx, page } = route === 'editor' ? await openEditor(browser, v.key) : await openLesson(browser, v.key)
      try {
        await expect(audienceBar(page)).toBeVisible({ timeout: 10_000 })
        const body = editorText(page)
        // authoring view first: the editable header shows who sees each section
        await expect(audienceBar(page)).toContainText('5 audience sections')
        await expect(page.getByText('Visible to:', { exact: true })).toHaveCount(4)
        await expect(page.getByText('Hidden from:', { exact: true })).toHaveCount(1)
        for (const [i, p] of PREVIEW_PERSONAS.entries()) {
          await chooseView(page, p.label)
          await expect(audienceBar(page).getByRole('button', { name: 'Exit preview' })).toBeVisible()
          for (const k of p.visible) {
            await expect(body).toContainText(SECTIONS[k].body)
          }
          const hidden = HIDDEN_FOR(p.visible)
          for (const k of hidden) {
            await expect(body).not.toContainText(SECTIONS[k].body)
            await expect(body).not.toContainText(SECTIONS[k].heading)
          }
          // each hidden section is replaced by a dashed placeholder (author-only), not silently dropped
          await expect(page.getByText('Hidden for this viewer')).toHaveCount(hidden.length)
          await expect(page.locator('.ProseMirror p', { hasText: 'FIELDS Majlis:' })).toHaveText(
            `FIELDS Majlis: ${p.majlis ?? 'your Majlis'} Region: ${p.region ?? 'your region'} END`,
          )
          if (p.note) await expect(page.getByTestId('mka-note-unrecognized')).toBeVisible()
          else await expect(page.getByTestId('mka-note-unrecognized')).toHaveCount(0)
          if (i === 0) await screenshot(page, `11-${v.key}-${route}-preview-local-nazim`)
        }
        // As me: the admin / author account itself is unrecognized -> untargeted + Hide-from content only
        await chooseView(page, 'As me')
        await expect(body).toContainText(SECTIONS.hideNational.body)
        await expect(body).not.toContainText(SECTIONS.localTabligh.body)
        // Exit preview restores every section
        await audienceBar(page).getByRole('button', { name: 'Exit preview' }).click()
        for (const k of SECTION_KEYS) await expect(body).toContainText(SECTIONS[k].body)
        await expect(audienceBar(page)).toContainText('Everything (author view)')
      } finally {
        await ctx.close()
      }
    })
  })
}

for (const route of ['editor', 'learner'] as const) test(`admin can preview as a specific person on the ${route} page`, async ({ browser }) => {
  const s = seeded()
  const { ctx, page } = route === 'editor' ? await openEditor(browser, 'admin') : await openLesson(browser, 'admin')
  try {
    await audienceBar(page).getByRole('button', { name: /Viewing:/ }).click()
    await page.getByRole('button', { name: /A specific person/ }).click()
    await page.getByRole('textbox', { name: /Search by name or email/ }).fill(s.personas.regionalQaid.email.split('@')[0])
    await page.getByText(s.personas.regionalQaid.email).click()
    await expect(audienceBar(page).getByRole('button', { name: /Viewing:/ })).not.toContainText('Everything')
    const body = editorText(page)
    await expect(body).toContainText(SECTIONS.regionalQaids.body)
    await expect(body).not.toContainText(SECTIONS.localTabligh.body)
  } finally {
    await ctx.close()
  }
})
