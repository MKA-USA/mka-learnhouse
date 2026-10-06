/**
 * REST helpers for the MKA audience e2e, bound to the stack's API (not the generic E2E_API_URL).
 * Seeding goes through the real admin APIs only.
 */
import type { Stack } from './stack'

export class Api {
  private tokens = new Map<string, string>()
  constructor(public stack: Stack) {}

  async raw(method: string, path: string, token: string | null, body?: unknown, form?: FormData): Promise<{ status: number; text: string }> {
    const headers: Record<string, string> = {}
    if (token) headers.Authorization = `Bearer ${token}`
    let payload: BodyInit | undefined
    if (form) payload = form
    else if (body !== undefined) {
      headers['Content-Type'] = 'application/json'
      payload = JSON.stringify(body)
    }
    const res = await fetch(`${this.stack.apiV1}${path}`, { method, headers, body: payload })
    return { status: res.status, text: await res.text() }
  }

  async json<T = any>(method: string, path: string, token: string | null, body?: unknown, form?: FormData): Promise<T> {
    const r = await this.raw(method, path, token, body, form)
    if (r.status < 200 || r.status >= 300) throw new Error(`${method} ${path} -> ${r.status}: ${r.text.slice(0, 400)}`)
    return (r.text ? JSON.parse(r.text) : undefined) as T
  }

  /** Cached per email (the API allows 30 logins / 5 min / IP). */
  async login(email: string, password: string): Promise<string> {
    const hit = this.tokens.get(email)
    if (hit) return hit
    for (let attempt = 0; attempt < 3; attempt++) {
      const res = await fetch(`${this.stack.apiV1}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ username: email, password }),
      })
      if (res.status === 429) {
        await new Promise((r) => setTimeout(r, 10_000))
        continue
      }
      const data: any = await res.json()
      const token = data?.tokens?.access_token ?? data?.access_token
      if (!res.ok || !token) throw new Error(`login failed for ${email}: ${res.status}`)
      this.tokens.set(email, token)
      return token
    }
    throw new Error(`login rate-limited for ${email}`)
  }
}
