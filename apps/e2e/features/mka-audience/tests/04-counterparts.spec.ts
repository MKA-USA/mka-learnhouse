import { test, expect } from '@playwright/test'
import { PERSONAS } from '../personas'
import { openLesson, stackAvailable } from '../helpers'

test.skip(!stackAvailable(), 'MKA e2e stack is not running (apps/e2e/mka/stack.sh up)')

/**
 * Counterparts card per persona. Expected rows follow the frozen contract (§2.3 + amendments): national, regional
 * department Nazim, regional Qaid, local; a persona's own role is omitted. The seeded accounts live on e2e-tests.com,
 * so the contract's "omit a row equal to the viewer's own address" never applies here.
 */
for (const p of PERSONAS.filter((x) => x.key !== 'author')) {
  test(`${p.label}: counterparts card`, async ({ browser }) => {
    const { ctx, page } = await openLesson(browser, p.key)
    try {
      if (p.counterparts === null) {
        await expect(page.getByTestId('mka-counterparts-card')).toHaveCount(0)
        await expect(page.getByText('Counterparts appear once your role is recognized.')).toBeVisible()
        return
      }
      const card = page.getByTestId('mka-counterparts-card')
      await expect(card).toBeVisible()
      const rows = card.locator('li')
      await expect(rows).toHaveCount(p.counterparts.length)
      for (const [i, want] of p.counterparts.entries()) {
        const row = rows.nth(i)
        await expect(row).toContainText(want.role_title)
        await expect(row.getByRole('link')).toHaveAttribute('href', `mailto:${want.email}`)
        await expect(row.getByRole('link')).toHaveText(want.email)
      }
    } finally {
      await ctx.close()
    }
  })
}
