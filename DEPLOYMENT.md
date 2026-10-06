# Deployment Pipeline

This fork (`MKA-USA/mka-learnhouse`) runs LearnHouse for MKA USA. This file explains how code gets from this repo to the live sites, so humans and coding agents change the right things in the right order.

Read this before touching the Dockerfile, anything under `docker/`, or any CI/workflow file.

## TL;DR

- Two long-lived branches: `dev` (default) and `prod`.
- `dev` branch deploys to **https://ilm-dev.mkausa.org** (staging).
- `prod` branch deploys to **https://ilm.mkausa.org** (production).
- Both are built **on the VPS by Coolify**, straight from this repo's root `Dockerfile`. There is no registry and no pushed image.
- A push to `dev` auto-deploys to ilm-dev via the `mka-dev-deploy` GitHub Actions workflow (it restarts the dev service in Coolify, which rebuilds from the branch). A push or merge to `prod` does **not** deploy immediately: prod deploys are batched and run hourly by `mka-prod-deploy`.
- Ship flow: commit to `dev` -> auto-deploys to ilm-dev -> test -> PR `dev` into `prod` -> merge (anytime) -> next hourly `mka-prod-deploy` run rebuilds prod.

## Environments

| | Dev | Prod |
|---|---|---|
| URL | https://ilm-dev.mkausa.org | https://ilm.mkausa.org |
| Git branch | `dev` | `prod` |
| Coolify environment | `development` | `production` (project "National Tools") |
| Database / Redis / volumes | Own, separate, started empty | Real user data |
| Purpose | Build and test changes | Live site |

Dev started as a clone of prod's Coolify service but has its own empty database and volumes. Nothing in dev touches prod data.

## How the build works

Each environment is a Coolify "Docker Compose service" with three containers: `learnhouse-app`, `db` (pgvector/pgvector:pg16) and `redis` (redis:7.2.3-alpine).

Only `learnhouse-app` is built from this repo. In the Coolify compose file its image line is replaced with a git build context:

```yaml
services:
  learnhouse-app:
    build:
      context: 'https://github.com/MKA-USA/mka-learnhouse.git#dev'   # '#prod' on production
      dockerfile: Dockerfile
    restart: unless-stopped
    # environment, volumes, etc. unchanged from the stock LearnHouse compose
```

The `#dev` / `#prod` suffix is the branch Docker clones and builds. `db` and `redis` stay on stock images.

The root `Dockerfile` is a multi-stage build that produces one all-in-one image:

- Next.js frontend (Bun), standalone output
- Python API (uv), run behind nginx
- Collab server (Bun/TypeScript)
- Final stage is `python:alpine`, runs `docker/start.sh`
- Listens on ports 80 (nginx), 9000 (API), 4000 (collab). Coolify routes the domain to port 80.

### Environment variables are runtime, not build time

`NEXT_PUBLIC_*` values are **not** baked in at build. `apps/web/server-wrapper.js` collects them from the container environment at start and writes the runtime config the frontend reads. The only `NEXT_PUBLIC_*` value fixed in the image is `NEXT_PUBLIC_LEARNHOUSE_OSS=true`.

Consequences:

- Do not add build args for domains, URLs or orgs. Config differences between dev and prod live entirely in Coolify's environment variables.
- Changing a domain or URL is an env var change plus a restart, not a rebuild-from-code change.
- Never commit secrets or `.env` files. The Dockerfile deletes `.env*` from the web build on purpose.

Secrets and per-environment config (JWT, NextAuth, DB password, admin password, domains, etc.) are managed in Coolify only. They are not in this repo. Note that dev's secrets were originally copied from prod and have not been regenerated yet.

## Shipping a change

1. Branch from `dev` or commit to `dev`. Keep changes compatible with the all-in-one image and the ports above.
2. Pushing to `dev` triggers `mka-dev-deploy`, which restarts the **dev** service in Coolify (the compose uses `build:`, so the restart rebuilds from the current `dev` branch) and waits for `/api/v1/health` to return 200. Docs-only pushes (`**.md`, `.codebase-memory/**`, `.qwen/**`) are skipped; use "Run workflow" to deploy manually.
3. Test on https://ilm-dev.mkausa.org. Check the home page loads, login works, and whatever you changed.
4. Open a pull request from `dev` into `prod`. `prod` is protected: a PR is required, force-pushes and deletion are blocked. No approval count is required, so the repo owner can merge their own PR.
5. After merge, nothing happens immediately. The hourly `mka-prod-deploy` run notices `prod` moved and restarts the **prod** service (rebuild from `prod`). For an immediate deploy use the urgent path below. Multiple merges within the hour produce one rebuild.
6. Verify https://ilm.mkausa.org loads and `/api/v1/health` returns 200.

Never push directly to `prod`, and never point prod at `#dev`.

### Prod deploys (hourly, batched)

`mka-prod-deploy` runs at the top of every hour (`0 * * * *`, UTC) and on manual dispatch.

- **Merge anytime.** Merging a `dev` -> `prod` PR never deploys by itself. Merging stays manual; no workflow merges PRs.
- **Marker tag.** Git tag `prod-deployed` points at the last successfully deployed `prod` SHA. If `prod` HEAD equals the tag, the run exits with "nothing to deploy". If the tag is missing, it counts as never deployed and deploys. Otherwise the job summary lists `git log prod-deployed..prod` and warns if `apps/api/migrations/**` changed (informational; it still deploys). The tag moves only after the health check passes, so a failed deploy is retried next hour.
- **Urgent deploy:** Actions > `mka-prod-deploy` > Run workflow with `urgent=true` (ignores the freeze). `force=true` redeploys even if prod HEAD equals the tag.
- **Freeze:** `gh variable set PROD_FREEZE --body true` makes scheduled runs and non-urgent dispatches skip (green run, logged). Unfreeze with `gh variable delete PROD_FREEZE`. Freeze before MKA events.
- **Setup:** a GitHub Environment named `production` with secrets `COOLIFY_URL`, `COOLIFY_TOKEN` and `COOLIFY_PROD_SERVICE_UUID`. The workflow needs `contents: write` only to move the tag.
- **Default-branch requirement:** scheduled workflows only fire from the default branch, so this file must live on `dev`. The job explicitly checks out `prod` and uses the `mka-wait-healthy` action from the default-branch checkout (it may not exist on `prod`).
- **Known risk:** the prod deploy and a dev build can run at the same time on the same VPS (the `deploy-prod` and `deploy-dev` concurrency groups are independent). Concurrent builds may exhaust RAM and slow or fail prod. Avoid pushing to `dev` near the top of the hour, or freeze prod while iterating.

## Rolling back

Prod: either revert the merge on `prod` and restart the prod service, or temporarily edit prod's compose to use the stock image (`image: 'ghcr.io/learnhouse/app:<tag>'` in place of the `build:` block) and restart. Pin an explicit tag if you do this; `latest` moves.

Database: prod has a daily Coolify backup of the `db` container, stored locally on the VPS (not S3). It covers the database only, not uploaded files in volumes. Restore from Coolify's Backups tab if a bad deploy ran a migration against prod data.

## Operational notes and gotchas

- **Build time and downtime.** A rebuild takes roughly 10 to 15 minutes cold, and the service is down or degraded while it runs. Restarting prod means a few minutes of downtime at minimum. Avoid restarting prod during MKA events.
- **No build logs in the Coolify UI.** For compose services, Coolify has no deployments log. While building, containers show Exited or Degraded. After it finishes, a "Service Startup" log appears. Judge success by status going back to Running (healthy) and the site loading.
- **Server size.** The VPS builds and runs prod and dev side by side. RAM was never measured; if builds start failing or prod slows during a build, suspect memory and avoid building dev and prod at the same time.
- **Coolify UI is slow.** Dropdowns and dialogs lag by several seconds. Wait and re-check before clicking Confirm. A restart Confirm click that lands too early may silently do nothing, so verify the restart actually happened (status change or startup log).
- **Saving the compose file.** After "Validate", a toast can cover the Save button. Dismiss it first, and confirm you see a "Service saved" toast.
- **Changes pending badge** in Coolify is unreliable. It can persist after a successful deploy.
- **Volume names** are prefixed with the service UUID on save, so dev and prod volumes cannot collide.

## CI / GitHub Actions

Actions is enabled on this fork for deploying dev and prod.

- **`mka-dev-deploy`** (`.github/workflows/mka-dev-deploy.yaml`) runs on push to `dev` (ignoring `**.md`, `.codebase-memory/**`, `.qwen/**`) and on manual dispatch. It runs install, `lint:strict` and `bun test tests` in `apps/web` (currently non-blocking because the baseline on `dev` fails both; remove `continue-on-error` once fixed), calls Coolify's API to restart the dev service, then polls https://ilm-dev.mkausa.org/api/v1/health via the `mka-wait-healthy` composite action (`.github/actions/mka-wait-healthy`). Runs are serialized (`deploy-dev` concurrency group, never cancelled mid-deploy).
- **Required setup:** a GitHub Environment named `development` with secrets `COOLIFY_URL`, `COOLIFY_TOKEN` and `COOLIFY_DEV_SERVICE_UUID`. Never commit these values.
- **`mka-prod-deploy`** (`.github/workflows/mka-prod-deploy.yaml`) is the hourly batched prod deploy described under "Prod deploys". Merging dev -> prod PRs stays manual; no workflow may merge PRs.
- **Inherited upstream workflows must stay disabled** where they publish: `release`, `build-community`, `cli-publish` and `notify-infra` are hardcoded to push images/packages upstream and would fail or push to the wrong registry. Keep them disabled with `gh workflow disable <name>`. (Upstream's lint/test workflows are harmless.)
- **No workflow may build or push images.** The image is built on the VPS by Coolify. Do not change this unless the deploy model is deliberately changed.
- Pulling upstream changes is done by merging upstream into `dev`.

## Rules for coding agents

- Do change application code on `dev` and open PRs `dev` -> `prod`. Do not commit to `prod` directly.
- Do not edit the `Dockerfile` ports (80/9000/4000), `docker/start.sh` or `docker/nginx.conf` casually. Coolify and the reverse proxy depend on port 80, and the `HOSTNAME`, `PORT`, `LEARNHOUSE_PORT` and `COLLAB_PORT` defaults.
- Do not add build-time args for `NEXT_PUBLIC_*`. Use the runtime wrapper.
- Do not commit secrets, `.env` files, hostnames of internal services, or Coolify details beyond what is in this file.
- Do not add or enable GitHub Actions workflows that build or push images, and do not re-enable the inherited `release`, `build-community`, `cli-publish` or `notify-infra` workflows. New workflows must be prefixed `mka-`.
- Dev deploys itself when `dev` is pushed (`mka-dev-deploy`). Prod deploys hourly after the owner merges to `prod` (`mka-prod-deploy`). Never merge PRs or trigger prod deploys yourself. When you finish a change, say whether it needs a prod deploy (and note dev will auto-deploy on push).
- If a change needs a new or changed environment variable, say so explicitly. It must be added in Coolify for each environment. It cannot be shipped through git.
- Database migrations run against real prod data on the first prod start after the next hourly deploy. Flag any migration in your PR description and test it on dev first.

## Email and Google SSO environment variables (Coolify, per environment)

Set these in Coolify for each environment (dev and prod). Values and secrets never go in the repo. Env changes take effect after a restart of the service; no rebuild is needed.

**Email (Brevo SMTP)**
- `LEARNHOUSE_EMAIL_PROVIDER=smtp`
- `LEARNHOUSE_SYSTEM_EMAIL_ADDRESS`
- `LEARNHOUSE_SYSTEM_EMAIL_SENDER_NAME`
- `LEARNHOUSE_SMTP_HOST=smtp-relay.brevo.com`
- `LEARNHOUSE_SMTP_PORT=587`
- `LEARNHOUSE_SMTP_USERNAME`
- `LEARNHOUSE_SMTP_PASSWORD`
- `LEARNHOUSE_SMTP_USE_TLS=true`

**Google SSO**
- `LEARNHOUSE_GOOGLE_CLIENT_ID`
- `LEARNHOUSE_GOOGLE_CLIENT_SECRET`
- Authorized redirect URI per environment: `https://<domain>/auth/callback/google`. Use separate OAuth clients and redirects for dev and prod.
- Google sign-in is open to everyone: any Google account (including personal Gmail) may sign in, which is how public learners join.

**Google-only domains (mkausa.org)**
- `MKA_GOOGLE_ONLY_DOMAINS=mkausa.org` — set in BOTH dev and prod. Comma-separated, case-insensitive, exact domain match only (no subdomains). Read at request time; restart after changing.
- Any account with an `@mkausa.org` address can authenticate ONLY through Google, so suspending the user in Google Workspace removes their access. Password login, signup, invite signup, password reset (request and completion), magic links, and email changes into or out of the domain are all refused for these addresses (403, "Accounts with an mkausa.org email must sign in with Google"; reset/magic-link requests return the normal generic success response and send nothing).
- Google sign-in with an `@mkausa.org` address additionally requires Google's Workspace `hd` claim to equal `mkausa.org`; a consumer Google account that merely uses an @mkausa.org address is rejected.
- If unset or empty there is no enforcement and mkausa.org users can still use passwords.
- Existing mkausa.org accounts with a password keep working through Google (matched by email); only their password login is blocked.
- Limitation: suspending a user in Google does not revoke a LearnHouse session already issued (access token 8 h, refresh up to 30 days of inactivity, `LEARNHOUSE_AUTH_REFRESH_TOKEN_DAYS`, minimum 14). See the session notes in the project history.
- Implementation: `apps/api/src/services/auth/mka_google_only.py`; hook sites listed in `.codebase-memory/upstream-modifications.md`.

**Local dev (signup proxy)**
- Outside the container the API runs on port 1338, but the signup route calls the API on loopback `http://127.0.0.1:9000` by default (non-SaaS only, no fallback), which gives a 502 locally. Set `LEARNHOUSE_INTERNAL_API_URL=http://127.0.0.1:1338/api/v1/` in `apps/web/.env.local`.

## Reference

- Upstream: LearnHouse (`learnhouse/learnhouse`). This fork tracks it but ships its own image built from this repo.
- Fork: https://github.com/MKA-USA/mka-learnhouse
- Dev: https://ilm-dev.mkausa.org
- Prod: https://ilm.mkausa.org
