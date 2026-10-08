# promote.py: make prod match dev

One command that promotes dev to prod: code, env, compose, org settings, backfill.

    python3 custom/ops/promote.py                 # dry-run: prints the plan, writes nothing
    python3 custom/ops/promote.py --apply         # execute
    python3 custom/ops/promote.py --apply --skip-code
    python3 custom/ops/promote.py --only env,compose
    python3 custom/ops/promote.py --apply --urgent   # deploy even if PROD_FREEZE is on

Requires `gh` (authenticated), macOS `security`, and keychain item `MKA_Coolify_API_Key`.
Python 3 stdlib only. Secret values are never printed (key names and set/changed only).

## Execution order

env -> compose -> code (+deploy) -> org -> backfill. Env and compose go first so the deploy picks them up.
If env/compose changed but there is no code to promote, the prod service is restarted
(`POST /services/{uuid}/restart`) and the script waits for health.

1. **env**: copies every dev key to prod via the Coolify API. Values containing `ilm-dev.mkausa.org`
   are rewritten to `ilm.mkausa.org`. Prod-only keys are reported, never deleted.
   Per-env keys are never copied; edit `PER_ENV_KEYS` (keep prod's value), `PER_ENV_SECRET_KEYS`
   (generated on prod with `secrets.token_hex(32)`, stored in keychain as `<KEY>_PROD`) or
   `PER_ENV_PREFIXES` (Coolify-generated `SERVICE_*`) at the top of `promote.py`.
2. **compose**: inserts env pass-through lines (`- VAR=...`) that exist in dev's compose but not prod's, next
   to their dev neighbours. Never touches the build ref (`#dev`/`#prod`) or domains. Backs prod's compose up to
   `~/.mka-promote/backups/prod-compose-<ts>.yml`, PATCHes it (base64), re-reads and asserts only the intended
   lines changed.
3. **code**: if dev is ahead of prod, opens (or reuses) a dev -> prod PR and merges it with a MERGE commit
   (never squash), dispatches `mka-prod-deploy.yaml`, polls every 30 s (cap 25 min), then health-checks
   https://ilm.mkausa.org/ and `/api/v1/health`.
4. **org**: diffs `GET /api/v1/orgs/slug/default` on dev vs prod (ignores ids, uuids, dates, plan, derived
   features; rewrites the dev host) and applies differences through the org admin API:
   `PUT /orgs/{id}` (name/description/about/label/email/links), `PUT /orgs/{id}/config/{color,font,footer_text,
   email_sender_name,default_language,watermark,auth_branding,seo,menu,signup-fields,course-end}`,
   `PUT /orgs/{id}/config/{ai,communities,payments,courses,folders,podcasts,boards,playgrounds}`,
   `PUT /orgs/{id}/signup_mechanism`, and image uploads `PUT /orgs/{id}/{logo,thumbnail,favicon,square_logo,
   og_image,auth_background}` (dev file downloaded from the media URL, skipped when bytes are identical).
   Paths with no wired endpoint (e.g. security toggles) are listed as MANUAL.
   Needs a prod admin API token in keychain `MKA_LH_PROD_API_TOKEN` (prod org settings -> API tokens -> Full Access):
   `security add-generic-password -U -s MKA_LH_PROD_API_TOKEN -a mka -w '<lh_token>'`. Without it the step is skipped.
5. **backfill**: `POST /mka/attributes/recompute` (if API tokens are rejected it prints the manual browser step),
   `POST /mka/identity/sync` dry-run then real (with `--apply`), then `GET /mka/identity/status`.

Tests: `python3 -m unittest custom/ops/test_promote.py` (from the repo root: `cd custom/ops && python3 -m unittest test_promote`).
