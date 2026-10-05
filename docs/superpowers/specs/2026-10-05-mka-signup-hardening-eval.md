# MKA signup hardening — evaluation (G1, G2, G3, G7)

Date: 2026-10-05 (revised after review of PR #19). Scope: backend Turnstile
enforcement and signup rate limit. Non-SaaS only: in SaaS mode
(`LEARNHOUSE_SAAS=true`) every fork rule below is inactive and behavior is
upstream's.

## Verdicts

| Gap | Verdict | Action |
|---|---|---|
| G1 Turnstile only in the Next proxy | Real bypass (direct `POST /api/v1/users/...`) | Enforce in the API for the 3 create-user routes via a fork dependency |
| G2 Google SSO account creation | Low risk | No limiter; documented (see below) |
| G3 `check_signup_rate_limit` unused | Real gap | Configurable fork limiter on the 3 create-user routes |
| G7 AMC-ID 409 enumeration oracle | Mitigated by G3 | No other change |

## Deployment topology (verified in code)

- One container: nginx :80 routes `/api/v1` to the API on `localhost:9000`
  (`docker/nginx.conf`); the API binds `0.0.0.0:${LEARNHOUSE_PORT}` (`app.py`,
  `Dockerfile` sets `LEARNHOUSE_PORT=9000`); pm2 starts web and API from one
  shell (`docker/start.sh`), so both read the same env.
- On MKA dev/prod `NEXT_PUBLIC_LEARNHOUSE_API_URL` is the PUBLIC URL, so
  `getServerAPIUrl()` made the Next signup route's server-side fetch leave the
  container and come back through the edge (Traefik -> nginx -> API). The API
  then saw the edge hop as the client and every signup would share one
  rate-limit bucket.
- Fix: outside SaaS the signup route calls the API on loopback
  (`LEARNHOUSE_INTERNAL_API_URL`, else `http://127.0.0.1:${LEARNHOUSE_PORT:-9000}/api/v1/`)
  and forwards the incoming `X-Forwarded-For` / `X-Real-IP` verbatim. If the
  loopback call fails while ESTABLISHING the connection (ECONNREFUSED,
  ENOTFOUND, EAI_AGAIN, EHOSTUNREACH, ENETUNREACH, EADDRNOTAVAIL, undici connect
  timeout) it falls back ONCE to the public URL. HTTP responses of any status,
  resets and timeouts are never retried (the API may have received the body).
- Host header: Node fetch ignores a `Host` override (tested), so on loopback
  the API sees `Host: 127.0.0.1:9000`. The create-user path does not use Host
  for routing or auth (no TrustedHost middleware; CSRF checks Origin/Referer,
  which the server-side call never sent before either). Host only feeds
  last-resort fallbacks for email links: `get_base_url_from_request` (after
  trusted Origin/Referer and `frontend_domain`) and `get_media_base_url` (org
  logo in emails; after `LEARNHOUSE_MEDIA_URL` / `LEARNHOUSE_BACKEND_URL` and a
  non-localhost `LEARNHOUSE_DOMAIN`). Check the welcome/verification email links
  and logo after deploy.

## G1 design: single verification in the API (option a)

A Turnstile token is single-use (a second siteverify returns
`timeout-or-duplicate`), so only one side may verify it.

- Non-SaaS: the Next signup route **does not verify**; it forwards the token in
  `X-Turnstile-Token` and the API verifies it once.
- Why (a) over (b) HMAC proof: one verifier, no new shared secret, no clock
  skew, no proof format to version, and it closes the direct-POST bypass with
  the same code path the browser uses.
- Enforcement rule (same as web): enforce only when BOTH
  `TURNSTILE_SECRET_KEY` and `NEXT_PUBLIC_TURNSTILE_SITE_KEY` are non-empty,
  read from `os.environ` at request time.
- 403 bodies are identical to the web's: missing token -> "Please complete the
  verification challenge."; invalid -> "Verification failed. Please try again."
- Fail mode: missing/invalid/oversized token is REJECTED. Cloudflare network
  errors, timeouts (5 s), HTTP >= 500, non-JSON replies and `success:false` with
  `internal-error` FAIL OPEN (logged): a Cloudflare outage must not take signups
  down.

### Who is checked (exemptions)

Exempt, validated identities only (from upstream `get_current_user`; garbage
bearer JWTs/cookies yield AnonymousUser, garbage `lh_` tokens 401):
- API-token callers (`APITokenUser`, `SuperadminAPITokenUser`);
- superadmins (DB lookup);
- an ADMIN (role 1) of the target org on `/users/{org_id}` and
  `/users/{org_id}/invite/{code}` (org taken from the path only).

`POST /users/` (org-less account) exempts superadmins only: an org-less account
belongs to no org, so being admin of some org confers no authority over it, and
on a multi-org instance "admin of any org" would be a self-service exemption.
Everyone else (anonymous, members, maintainers, admins of another org) gets
Turnstile + limiter. The e2e client (`apps/e2e/core/client.ts`) logs in as the
bootstrap admin (`setup.py` assigns `ADMIN_ROLE_ID` in the default org) and
posts to `/users/{org.id}`, so it stays exempt.

Login / forgot / reset: `/api/turnstile/verify` is client-enforced only.
Server-side enforcement needs the token threaded through upstream login and
reset endpoints. Not small; left documented. Backend limiters exist (login
30/5 min/IP, reset 5/5 min/email).

## G3 design: configurable signup limiter

- Fork wrapper over upstream `check_rate_limit` (Redis key `rate_limit:signup:{ip}`).
- `MKA_SIGNUP_RATE_LIMIT_PER_HOUR`, default `60`; `0` disables; invalid -> default.
- Runs AFTER Turnstile: only requests that passed Turnstile (or when Turnstile
  is not enforced) consume the bucket, so tokenless garbage cannot lock members
  out. With Turnstile enforced, a counted attempt costs a solved challenge.
- Skipped when the resolved client IP is not globally routable
  (loopback/private/link-local/unspecified/documentation/unknown): such an IP
  cannot tell members apart, so a shared bucket is never created.
- FAIL OPEN when Redis is unavailable or errors (logged).
- 429 `detail` "Too many sign-up attempts from your network. Please try again in
  about N minutes." plus `Retry-After`; the forms render any string `detail`.
- Client IP: fork `mka_client_ip` (see IP trust model).

## IP trust model

- Upstream `get_client_ip` trusts `X-Forwarded-For` only from a loopback/private
  direct peer and then takes its FIRST entry.
- The container nginx has no `real_ip` / `set_real_ip_from` directives and sets
  `X-Forwarded-For $proxy_add_x_forwarded_for`, i.e. it APPENDS its peer (the
  Traefik hop) to whatever XFF arrived. If Traefik (or Cloudflare in front of
  it) passes a client-supplied XFF through, the first entry is attacker-chosen:
  rotating it would mint a fresh bucket per request. The loopback Next -> API
  hop forwards the same header verbatim, so it does not change this.
- Fork fix (guard only; upstream `get_client_ip` and the login limiter are
  unchanged): `mka_client_ip` takes the RIGHT-MOST globally routable XFF entry
  when the direct peer is loopback/private. Entries on the right are appended
  by the proxy chain, so a client cannot choose them. Private entries (proxy
  hops) are skipped; with no global entry, or an empty/unknown IP, the limiter
  is skipped and never creates a key. A public direct peer is used as-is.
- Residual: if a CDN (e.g. Cloudflare proxy) sits in front of Traefik, the
  right-most global entry is the CDN edge, not the member, so buckets become
  per-edge (coarser, never spoofable). Because only Turnstile-passing requests
  count, filling a bucket costs solved challenges. If that is the topology,
  raise `MKA_SIGNUP_RATE_LIMIT_PER_HOUR` or set `0`.
- Turnstile `remoteip` uses the same IP.

## G2: Google SSO account creation

Not rate limited. A bot needs a real Google account per member account, and
`MKA_GOOGLE_ONLY_DOMAINS` already forces mkausa.org staff through Google. A
limiter would have to hook upstream `signWithGoogle` (where new vs existing is
known), and OAuth calls through the Next proxy have the same client-IP problem.
Revisit if abuse appears.

## New env vars

| Var | Where | Default | Effect |
|---|---|---|---|
| `MKA_SIGNUP_RATE_LIMIT_PER_HOUR` | API | `60` | Max Turnstile-passing create-user attempts per globally routable client IP per hour; `0` disables |
| `LEARNHOUSE_INTERNAL_API_URL` | web (optional) | unset -> `http://127.0.0.1:${LEARNHOUSE_PORT:-9000}/api/v1/` | Loopback API base the signup route uses outside SaaS |
| `TURNSTILE_SECRET_KEY` + `NEXT_PUBLIC_TURNSTILE_SITE_KEY` (existing) | both | unset | Both set -> API enforces Turnstile on guarded callers |
