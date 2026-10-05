# MKA signup hardening — evaluation (G1, G2, G3, G7)

Date: 2026-10-05. Scope: backend Turnstile enforcement and signup rate limit.
Non-SaaS only: in SaaS mode (`LEARNHOUSE_SAAS=true`) every fork rule below is
inactive and behavior is upstream's.

## Verdicts

| Gap | Verdict | Action |
|---|---|---|
| G1 Turnstile only in the Next proxy | Real bypass (direct `POST /api/v1/users/...`) | Enforce in the API for the 3 create-user routes via a fork dependency |
| G2 Google SSO account creation | Low risk | No limiter; documented (see below) |
| G3 `check_signup_rate_limit` unused | Real gap | Wire a configurable fork limiter into the 3 create-user routes |
| G7 AMC-ID 409 enumeration oracle | Mitigated by G3 | No other change |

## G1 design: single verification in the API (option a)

A Turnstile token is single-use (a second siteverify returns
`timeout-or-duplicate`), so only one side may verify it.

- Non-SaaS: the Next signup route **stops verifying** and forwards the token in
  the `X-Turnstile-Token` header. The API verifies it once.
- Why (a) over (b) HMAC proof: one verifier, no new shared secret, no clock
  skew, no proof format to version, and it closes the direct-POST bypass with
  the same code path the browser uses. The web and the API run in one
  container started from one shell (`docker/start.sh` via pm2), so both read the
  same `TURNSTILE_SECRET_KEY` / `NEXT_PUBLIC_TURNSTILE_SITE_KEY`.
- Enforcement rule (same as web): enforce only when BOTH keys are non-empty,
  read from `os.environ` at request time. A half-configured deployment never
  locks out signups.
- Applies only to ANONYMOUS callers. Authenticated callers (session or API
  token, e.g. the e2e client `apps/e2e/core/client.ts` that creates students
  with an admin bearer token) are exempt from Turnstile and from the limiter:
  they cannot carry a browser challenge, and they are accountable. Residual: a
  logged-in member could script account creation with their own session.
- 403 bodies are identical to the web's: missing token -> "Please complete the
  verification challenge."; invalid -> "Verification failed. Please try again."
  The proxy mirrors the backend status + JSON, so the forms show them unchanged.
- Fail mode: missing or invalid token is REJECTED (fail closed). Cloudflare
  network errors, timeouts (5 s) or non-JSON replies FAIL OPEN (logged), same as
  upstream's Next helper: a Cloudflare outage must not take signups down, and
  the rate limiter still bounds abuse during an outage.
- Client IP for `remoteip`: the limiter's `get_client_ip` (below).
- HTTP client: `httpx` (already a dependency).

Login / forgot / reset: `/api/turnstile/verify` is client-enforced only.
Server-side enforcement needs the token threaded through upstream login and
reset endpoints (several upstream files). Not small; left documented. Those
paths already have backend limiters (login 30/5 min/IP, reset 5/5 min/email).

## G3 design: configurable signup limiter

- Fork wrapper over upstream `check_rate_limit` (same Redis key family
  `signup:{ip}`), not upstream's hard-coded 10/hour.
- `MKA_SIGNUP_RATE_LIMIT_PER_HOUR`, default `30`; `0` disables; invalid -> default.
- Counts every anonymous create-user attempt (this is what bounds the AMC-ID
  409 oracle), runs BEFORE Turnstile so a bot cannot burn siteverify calls.
- FAIL OPEN when Redis is unavailable or errors (logged).
- 429 with `detail` "Too many sign-up attempts from your network. Please try
  again in about N minutes." and `Retry-After`. The forms render any string
  `detail` for non-2xx.
- Client IP: upstream `get_client_ip` (same as login): trusts
  `X-Forwarded-For` / `X-Real-IP` only when the direct peer is loopback/private.
- Next proxy: the signup route calls the API server-side from inside the
  container, so the API saw 127.0.0.1 for every signup (one shared bucket). The
  route now forwards the incoming `X-Forwarded-For` / `X-Real-IP` headers
  verbatim, giving the API exactly what it would see on a direct request
  through the container nginx. Spoof resistance equals login's: it depends on
  the edge proxy (Traefik/nginx) appending the real peer.

## G2: Google SSO account creation

Not rate limited. A bot needs a real Google account per member account (phone
verification, Google's own abuse controls), and `MKA_GOOGLE_ONLY_DOMAINS`
already forces mkausa.org staff through Google. A limiter would have to hook
the upstream `signWithGoogle` service (where new vs existing is known) and the
OAuth call often reaches the API through the Next proxy (loopback IP), so a
per-IP bucket would be shared by every member. Cost and false-positive risk
outweigh the benefit. Revisit if abuse appears.

## New env vars (API)

| Var | Default | Effect |
|---|---|---|
| `MKA_SIGNUP_RATE_LIMIT_PER_HOUR` | `30` | Max anonymous create-user attempts per client IP per hour; `0` disables |
| `TURNSTILE_SECRET_KEY` + `NEXT_PUBLIC_TURNSTILE_SITE_KEY` (existing) | unset | Both set -> API enforces Turnstile on anonymous signup |
