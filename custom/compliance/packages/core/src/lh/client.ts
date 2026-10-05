import { LhConfigError, LhHttpError, LhNetworkError, redactPath } from "./errors";

export interface LhClientOptions {
  baseUrl: string;
  token: string;
  orgSlug: string;
  /** Minimum gap between requests (politeness). Default 1000ms. */
  delayMs?: number;
  maxRetries?: number;
  backoffBaseMs?: number;
  timeoutMs?: number;
  fetch?: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
  /** Receives only "METHOD redacted-path status" lines. Never bodies or tokens. */
  log?: (line: string) => void;
}

export interface RequestOptions {
  query?: Record<string, string | number | boolean | undefined>;
  json?: unknown;
  form?: FormData;
  /** Per-request timeout override (uploads). */
  timeoutMs?: number;
}

const RETRY_STATUS = new Set([429, 502, 503, 504]);

export class LhClient {
  readonly baseUrl: string;
  readonly orgSlug: string;
  private readonly token: string;
  private readonly delayMs: number;
  private readonly maxRetries: number;
  private readonly backoffBaseMs: number;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;
  private readonly sleep: (ms: number) => Promise<void>;
  private readonly log?: (line: string) => void;
  private lastRequestAt = 0;

  constructor(o: LhClientOptions) {
    if (!o.baseUrl) throw new LhConfigError("LH_API_BASE is required");
    if (!o.token) throw new LhConfigError("LH_API_TOKEN is required");
    this.baseUrl = o.baseUrl.replace(/\/+$/, "");
    this.token = o.token;
    this.orgSlug = o.orgSlug;
    this.delayMs = o.delayMs ?? 1000;
    this.maxRetries = o.maxRetries ?? 3;
    this.backoffBaseMs = o.backoffBaseMs ?? 500;
    this.timeoutMs = o.timeoutMs ?? 30_000;
    this.fetchImpl = o.fetch ?? fetch;
    this.sleep = o.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
    this.log = o.log;
  }

  static fromEnv(env: Record<string, string | undefined> = process.env, extra: Partial<LhClientOptions> = {}): LhClient {
    return new LhClient({
      baseUrl: env.LH_API_BASE ?? "", token: env.LH_API_TOKEN ?? "", orgSlug: env.LH_ORG_SLUG ?? "", ...extra,
    });
  }

  /** Never serialize the token (e.g. via console.log(client) or JSON.stringify). */
  toJSON() { return { baseUrl: this.baseUrl, orgSlug: this.orgSlug }; }
  [Symbol.for("nodejs.util.inspect.custom")]() { return `LhClient(${this.baseUrl}, org=${this.orgSlug})`; }

  private url(path: string, query?: RequestOptions["query"]): string {
    const u = new URL(this.baseUrl + (path.startsWith("/") ? path : `/${path}`));
    for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined) u.searchParams.set(k, String(v));
    return u.toString();
  }

  async request<T = unknown>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
    const safePath = redactPath(path);
    const headers: Record<string, string> = { Authorization: `Bearer ${this.token}`, Accept: "application/json" };
    let body: BodyInit | undefined;
    if (opts.form) body = opts.form;
    else if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.json); }
    const idempotent = method === "GET" || method === "PUT" || method === "DELETE" || method === "HEAD";
    const url = this.url(path, opts.query);

    let attempt = 0;
    for (;;) {
      attempt++;
      const wait = this.lastRequestAt + this.delayMs - Date.now();
      if (wait > 0) await this.sleep(wait);
      this.lastRequestAt = Date.now();

      let res: Response;
      try {
        res = await this.fetchImpl(url, { method, headers, body, signal: AbortSignal.timeout(opts.timeoutMs ?? this.timeoutMs) });
      } catch (e) {
        if (idempotent && attempt <= this.maxRetries) { await this.sleep(this.backoff(attempt)); continue; }
        throw new LhNetworkError(method, safePath, attempt, e);
      }
      this.log?.(`${method} ${safePath} ${res.status}`);

      if (res.ok) {
        if (res.status === 204) return undefined as T;
        const text = await res.text();
        return (text ? JSON.parse(text) : undefined) as T;
      }
      const retryable = RETRY_STATUS.has(res.status) && (idempotent || res.status === 429 || res.status === 503);
      if (retryable && attempt <= this.maxRetries) {
        const ra = Number(res.headers.get("retry-after"));
        await res.body?.cancel();
        await this.sleep(Number.isFinite(ra) && ra > 0 ? Math.min(ra * 1000, 60_000) : this.backoff(attempt));
        continue;
      }
      let detail: string | undefined;
      try {
        const j = (await res.json()) as { detail?: unknown };
        if (typeof j?.detail === "string") detail = j.detail.slice(0, 300);
      } catch { /* non-JSON body */ }
      throw new LhHttpError(method, safePath, res.status, detail);
    }
  }

  private backoff(attempt: number): number {
    return this.backoffBaseMs * 2 ** (attempt - 1) + Math.floor(Math.random() * 100);
  }

  get<T = unknown>(path: string, query?: RequestOptions["query"]) { return this.request<T>("GET", path, { query }); }
  post<T = unknown>(path: string, json?: unknown, query?: RequestOptions["query"]) { return this.request<T>("POST", path, { json, query }); }
  put<T = unknown>(path: string, json?: unknown) { return this.request<T>("PUT", path, { json }); }
  del<T = unknown>(path: string) { return this.request<T>("DELETE", path); }
}
