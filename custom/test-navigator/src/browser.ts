// Launch helper: reuse the Chromium already cached by apps/e2e's Playwright install (any revision).
import { chromium, type Browser, type BrowserContext, type Page } from 'playwright-core'
import { existsSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

function findChromium(): string | undefined {
  const root = join(homedir(), 'Library/Caches/ms-playwright')
  if (!existsSync(root)) return undefined
  const dirs = readdirSync(root).filter((d) => /^chromium_headless_shell-\d+$/.test(d)).sort().reverse()
  for (const d of dirs) {
    for (const sub of ['chrome-headless-shell-mac-arm64', 'chrome-headless-shell-mac-x64']) {
      const p = join(root, d, sub, 'chrome-headless-shell')
      if (existsSync(p)) return p
    }
  }
  return undefined
}

export async function launch(): Promise<Browser> {
  return chromium.launch({ headless: true, executablePath: process.env.TN_CHROMIUM ?? findChromium() })
}

export async function newPage(browser: Browser, viewport = { width: 1280, height: 900 }): Promise<{ ctx: BrowserContext; page: Page }> {
  const ctx = await browser.newContext({ viewport })
  return { ctx, page: await ctx.newPage() }
}
