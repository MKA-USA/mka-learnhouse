/**
 * Where the throwaway local stack lives (written by apps/e2e/mka/stack.sh up).
 *
 * The MKA audience specs run against a REAL local stack (real API + real web, no mock layer). When the stack JSON is
 * absent (for example the default `playwright test` run in CI, which boots a vanilla self-host) the specs skip.
 */
import { existsSync, readFileSync } from 'node:fs'

export const STACK_JSON = process.env.MKA_E2E_STACK_JSON || '/private/tmp/claude-501/mka-e2e-stack.json'

export interface Stack {
  webUrl: string
  apiV1: string
  orgSlug: string
  adminEmail: string
  stateDir: string
}

export function loadStack(): Stack | null {
  if (!existsSync(STACK_JSON)) return null
  try {
    const raw = JSON.parse(readFileSync(STACK_JSON, 'utf8'))
    return {
      webUrl: raw.webUrl,
      apiV1: raw.apiV1,
      orgSlug: raw.orgSlug,
      adminEmail: raw.adminEmail,
      stateDir: raw.stateDir,
    }
  } catch {
    return null
  }
}

export function requireStack(): Stack {
  const s = loadStack()
  if (!s) throw new Error(`MKA e2e stack not running (no ${STACK_JSON}). Run apps/e2e/mka/stack.sh up first.`)
  return s
}

/** The bootstrapped admin's password lives in the stack's secrets file (never committed). */
export function adminPassword(stack: Stack): string {
  const text = readFileSync(`${stack.stateDir}/secrets.env`, 'utf8')
  const m = text.match(/^LEARNHOUSE_INITIAL_ADMIN_PASSWORD=(.*)$/m)
  if (!m) throw new Error('admin password not found in secrets.env')
  return m[1]
}
