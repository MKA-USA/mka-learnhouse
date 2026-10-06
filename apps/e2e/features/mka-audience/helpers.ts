/**
 * Shared helpers for the MKA audience specs: read the seeded fixture, open the lesson as a persona (saved
 * storageState from global setup), wait until the page has settled, and collect screenshots into docs/.
 */
import { expect } from '@playwright/test'
import type { Browser, BrowserContext, Page } from '@playwright/test'
import { existsSync, mkdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { SECTIONS } from './fixture'
import type { SectionKey, PersonaKey } from './personas'
import type { Seeded } from './seed'
import { SEED_FILE } from './seed'
import { loadStack } from './stack'

export const SCREEN_DIR = fileURLToPath(new URL('../../../../docs/screens/audience/e2e/', import.meta.url))

export const stackAvailable = (): boolean => {
  const s = loadStack()
  return !!s && existsSync(SEED_FILE(s.stateDir))
}

let cached: Seeded | null = null
/** The fixture written by global setup (fresh per run). */
export function seeded(): Seeded {
  if (cached) return cached
  const s = loadStack()
  if (!s) throw new Error('MKA e2e stack is not running')
  cached = JSON.parse(readFileSync(SEED_FILE(s.stateDir), 'utf8')) as Seeded
  return cached
}

export interface Opened {
  ctx: BrowserContext
  page: Page
}

export async function newPersonaContext(browser: Browser, key: PersonaKey, opts: { width?: number; height?: number } = {}): Promise<BrowserContext> {
  const s = seeded()
  return browser.newContext({
    storageState: s.personas[key].storageState,
    viewport: { width: opts.width ?? 1280, height: opts.height ?? 900 },
  })
}

export const editorText = (page: Page) => page.locator('.ProseMirror').first()

/**
 * Resolves once the lesson has rendered AND the viewer attributes request (`/mka/attributes/me`) has completed AND the
 * editor text has stopped changing for two consecutive reads. Sections render nothing while that request is pending, so
 * "settled" is the only state where "absent" means "evaluated hidden".
 */
export async function settle(page: Page): Promise<void> {
  await expect(editorText(page)).toContainText('ZQ-BODY-UNTARGETED', { timeout: 30_000 })
  let last = ''
  let stable = 0
  const deadline = Date.now() + 20_000
  while (stable < 3 && Date.now() < deadline) {
    const now = (await editorText(page).innerText()) + '||' + (await page.locator('[data-testid^="mka-"]').count())
    stable = now === last ? stable + 1 : 0
    last = now
    await page.waitForTimeout(250)
  }
  expect(stable, 'lesson text never settled').toBeGreaterThanOrEqual(3)
}

/** Opens the learner page as `key` and settles. The caller closes `ctx`. */
export async function openLesson(browser: Browser, key: PersonaKey, opts: { width?: number; height?: number } = {}): Promise<Opened> {
  const ctx = await newPersonaContext(browser, key, opts)
  const page = await ctx.newPage()
  await page.goto(seeded().learnerUrl)
  await settle(page)
  return { ctx, page }
}

export const markers = (keys: SectionKey[]) => keys.flatMap((k) => [SECTIONS[k].heading, SECTIONS[k].body])

export async function screenshot(page: Page, name: string): Promise<void> {
  mkdirSync(SCREEN_DIR, { recursive: true })
  await page.screenshot({ path: `${SCREEN_DIR}${name}.png`, fullPage: true })
}

/** The DOM as a string with the table of contents removed (the TOC has its own spec). */
export async function pageHtmlWithoutToc(page: Page): Promise<string> {
  return page.evaluate(() => {
    const clone = document.documentElement.cloneNode(true) as HTMLElement
    clone.querySelectorAll('.toc-item').forEach((el) => el.closest('ul')?.remove())
    return clone.outerHTML
  })
}

export const audienceBar = (page: Page) => page.getByRole('region', { name: 'Audience preview' })

/**
 * Opens the activity in the real editor as `key` (admin or author). On the editor page the document-level Audience
 * chrome (the bar) mounts on every load; on the learner page it does not (FINDING-0 in FINDINGS.md), so everything that
 * needs the bar (Preview-as, authoring) is driven from the editor.
 */
export async function openEditor(browser: Browser, key: PersonaKey, opts: { width?: number; height?: number } = {}): Promise<Opened> {
  const ctx = await newPersonaContext(browser, key, { width: opts.width ?? 1400, height: opts.height ?? 1000 })
  const page = await ctx.newPage()
  await page.goto(seeded().editorUrl)
  await expect(editorText(page)).toContainText('ZQ-BODY-UNTARGETED', { timeout: 30_000 })
  await expect(audienceBar(page)).toBeVisible({ timeout: 15_000 })
  return { ctx, page }
}
