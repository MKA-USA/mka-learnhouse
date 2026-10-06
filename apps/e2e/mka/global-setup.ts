/**
 * Global setup for the MKA audience e2e: seeds personas + the fixture course through the real APIs, then logs each
 * persona in ONCE through the real login form and saves a storageState per persona (8 logins per run; the API allows
 * 30 / 5 min / IP, so run `stack.sh reset-ratelimit` between back-to-back runs if you also seed a lot).
 */
import { chromium } from '@playwright/test'
import type { Browser } from '@playwright/test'
import { spawnSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { dirname } from 'node:path'
import { requireStack } from '../features/mka-audience/stack'
import { seed } from '../features/mka-audience/seed'

const ONBOARDING = JSON.stringify({
  completedSteps: ['create_course', 'add_activities', 'experience_editor', 'try_playgrounds', 'invite_users', 'customize_org', 'teach_the_world'],
  skippedSteps: [], minimized: true, expanded: false, showAllSteps: false, dismissed: true, welcomeSeen: true,
})

async function saveLogin(browser: Browser, webUrl: string, email: string, password: string, statePath: string) {
  mkdirSync(dirname(statePath), { recursive: true })
  const context = await browser.newContext()
  const page = await context.newPage()
  for (let attempt = 1; attempt <= 3; attempt++) {
    await page.goto(`${webUrl}/login`)
    await page.getByRole('textbox', { name: 'Email' }).fill(email)
    await page.getByRole('textbox', { name: 'Password' }).fill(password)
    await page.getByRole('button', { name: 'Login', exact: true }).click()
    try {
      await page.waitForURL((u) => !/\/login(\?|$)/.test(u.toString()), { timeout: 15_000 })
      break
    } catch {
      if (attempt === 3) throw new Error(`global-setup: login failed for ${email}`)
      await page.waitForTimeout(10_000)
    }
  }
  await page.evaluate((v) => localStorage.setItem('lh_onboarding', v), ONBOARDING)
  await context.storageState({ path: statePath })
  await context.close()
}

export default async function globalSetup(): Promise<void> {
  const stack = requireStack()
  // Best effort: 3 back-to-back runs would otherwise brush the 30-logins / 5 min / IP limit of the throwaway API.
  spawnSync('bash', [new URL('./stack.sh', import.meta.url).pathname, 'reset-ratelimit'], { stdio: 'ignore' })
  const seeded = await seed()
  console.log(`MKA audience e2e: course ${seeded.courseUuid}, ${Object.keys(seeded.personas).length} personas seeded.`)
  const browser = await chromium.launch()
  try {
    for (const p of Object.values(seeded.personas)) {
      await saveLogin(browser, stack.webUrl, p.email, p.password, p.storageState)
    }
  } finally {
    await browser.close()
  }
}
