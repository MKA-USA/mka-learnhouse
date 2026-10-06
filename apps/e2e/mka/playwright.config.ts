import { defineConfig, devices } from '@playwright/test'
import { loadStack } from '../features/mka-audience/stack'

/**
 * Config for the deterministic MKA audience persona e2e (real local stack, no mock layer, no LLMs).
 *
 *   apps/e2e/mka/stack.sh up
 *   cd apps/e2e && bunx playwright test -c mka/playwright.config.ts
 *
 * Serial (workers: 1) because every spec reads the one seeded course and the authoring specs write to it. No retries:
 * the suite is a pass/fail gate and must be green without them.
 */
// Artifacts stay out of the repo (apps/e2e/.gitignore is an upstream file we do not touch).
const OUT = loadStack()?.stateDir ?? '/private/tmp/claude-501/mka-e2e'

export default defineConfig({
  testDir: '../features/mka-audience',
  globalSetup: './global-setup.ts',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  reporter: [['list'], ['html', { open: 'never', outputFolder: `${OUT}/report` }]],
  outputDir: `${OUT}/test-results`,
  use: {
    baseURL: loadStack()?.webUrl,
    trace: 'retain-on-failure',
    screenshot: 'off',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
