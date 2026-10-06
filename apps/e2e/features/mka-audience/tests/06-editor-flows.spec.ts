import { test, expect } from '@playwright/test'
import { Api } from '../api'
import { PERSONAS } from '../personas'
import { UNTARGETED } from '../fixture'
import { audienceBar, editorText, newPersonaContext, openEditor, screenshot, seeded, stackAvailable } from '../helpers'
import { requireStack } from '../stack'

test.skip(!stackAvailable(), 'MKA e2e stack is not running (apps/e2e/mka/stack.sh up)')

const NEW_BODY = 'ZQ-BODY-NEWSECTION-AUTHORED-w29'

/** Number of seeded personas whose override is a Local officeholder in Tabligh (the rule authored below). */
const expectedLocalTabligh = PERSONAS.filter((p) => p.override?.level === 'local' && p.override?.department === 'tabligh').length

test.describe.configure({ mode: 'serial' })

test('author inserts a section with /audience, picks Local + Tabligh, saves, and it survives a reload', async ({ browser }) => {
  const s = seeded()
  const { ctx, page } = await openEditor(browser, 'author')
  try {
    await page.locator('.ProseMirror p', { hasText: 'ZQ-BODY-VERSION2-TAIL' }).click()
    await page.keyboard.press('End')
    await page.keyboard.press('Enter')
    await page.keyboard.type('/audience')
    await expect(page.getByText('Audience section', { exact: true })).toBeVisible()
    await page.keyboard.press('Enter')

    const picker = page.getByRole('group', { name: 'Who should see this section?' }).first()
    await expect(picker).toBeVisible()
    await picker.getByRole('button', { name: 'Local officeholders' }).click()
    await picker.getByRole('button', { name: /Department.*Choose/i }).click()
    await page.getByRole('option', { name: 'Tabligh', exact: true }).click()
    // the department list is a multi-select and stays open: close it (Escape closes only the list, not the picker)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('option', { name: 'Tabligh', exact: true })).toBeHidden()
    await expect(picker).toBeVisible()

    // the picker's own count equals the number of seeded matching personas
    await expect(picker.getByTestId('audience-reads-as')).toHaveText('Local officeholders in Tabligh')
    const shown = picker.getByTestId('audience-count')
    await expect(shown).toContainText(new RegExp(`≈?\\s*${expectedLocalTabligh}\\s+(person|people)`))
    await screenshot(page, '20-author-picker-local-tabligh')

    // the API says the same thing (aggregate only)
    const api = new Api(requireStack())
    const token = await api.login(s.personas.author.email, s.personas.author.password)
    const count = await api.json<{ count: number }>('POST', '/mka/attributes/audience/count', token, {
      org_id: s.orgId,
      course_uuid: s.courseUuid,
      rule: { v: 1, mode: 'show', groups: [{ level: ['local'], department: ['tabligh'] }] },
    })
    expect(count.count).toBe(expectedLocalTabligh)

    await picker.getByRole('button', { name: 'Done' }).click()
    await expect(picker).toBeHidden()
    await page.keyboard.type(NEW_BODY)
    await page.getByText('Save', { exact: true }).first().click()

    // persisted through the real API with the exact rule
    await expect
      .poll(async () => {
        const a = await api.json<any>('GET', `/activities/${s.activityUuid}`, token)
        const secs = (a.content?.content ?? []).filter((n: any) => n.type === 'mkaAudience')
        const mine = secs.find((n: any) => JSON.stringify(n).includes(NEW_BODY))
        return mine ? JSON.stringify(mine.attrs.rule.groups) + mine.attrs.rule.mode : null
      }, { timeout: 20_000 })
      .toBe(JSON.stringify([{ level: ['local'], department: ['tabligh'] }]) + 'show')

    await page.reload()
    await expect(editorText(page)).toContainText(NEW_BODY, { timeout: 30_000 })
    await expect(audienceBar(page)).toContainText('6 audience sections')
    // header of the new section (the fixture already has one Local+Tabligh section, so two headers read this)
    await expect(page.getByText('Local officeholders in Tabligh', { exact: true })).toHaveCount(2)
    await expect(page.getByText('Visible to:', { exact: true })).toHaveCount(5)
    await screenshot(page, '21-author-after-reload')
  } finally {
    await ctx.close()
  }
})

test('the saved section is shown to a Local Nazim Tabligh and hidden from a Regional Qaid on the learner page', async ({ browser }) => {
  for (const [key, shouldSee] of [['localNazim', true], ['regionalQaid', false]] as const) {
    const ctx = await newPersonaContext(browser, key)
    const page = await ctx.newPage()
    try {
      await page.goto(seeded().learnerUrl)
      await expect(editorText(page)).toContainText(UNTARGETED.body, { timeout: 30_000 })
      if (shouldSee) await expect(editorText(page)).toContainText(NEW_BODY, { timeout: 15_000 })
      else {
        await page.waitForTimeout(1500)
        await expect(editorText(page)).not.toContainText(NEW_BODY)
      }
    } finally {
      await ctx.close()
    }
  }
})

for (const key of ['admin', 'author'] as const) {
  test(`${key}: version history preview of the activity is not blank`, async ({ browser }) => {
    const { ctx, page } = await openEditor(browser, key)
    try {
      await page.locator('svg.lucide-history').first().click()
      await expect(page.getByRole('heading', { name: /version history/i })).toBeVisible()
      const previews = page.locator('button[title]').filter({ has: page.locator('svg.lucide-eye') })
      await expect(previews.first()).toBeVisible()
      // every listed (older) version
      const n = await previews.count()
      for (let idx = 0; idx < n; idx++) {
        await previews.nth(idx).click()
        const preview = page.locator('.ProseMirror').last()
        await expect(preview).toContainText(UNTARGETED.body, { timeout: 15_000 })
        await expect(preview).toContainText('ZQ Untargeted Heading')
        expect((await preview.innerText()).trim().length).toBeGreaterThan(50)
        if (idx === 0) await screenshot(page, `22-${key}-version-preview`)
        await page.getByRole('button', { name: /^close$/i }).click()
        await expect(page.locator('.ProseMirror')).toHaveCount(1)
      }
    } finally {
      await ctx.close()
    }
  })
}

test('at 375px the editor is desktop-only, so the picker bottom sheet cannot be reached (FINDING-5)', async ({ browser }) => {
  const ctx = await newPersonaContext(browser, 'author', { width: 375, height: 800 })
  const page = await ctx.newPage()
  try {
    await page.goto(seeded().editorUrl)
    await expect(page.getByText('The editor is only accessible from a desktop device.')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('group', { name: 'Who should see this section?' })).toHaveCount(0)
    await screenshot(page, '23-editor-375px-desktop-only')
  } finally {
    await ctx.close()
  }
})
