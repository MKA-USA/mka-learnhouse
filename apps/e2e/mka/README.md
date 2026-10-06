# MKA Audience persona e2e (fork-only)

Deterministic Playwright specs (no LLMs) for the Audience block against a real throwaway local stack (real API, real web
production build, `NEXT_PUBLIC_MKA_AUDIENCE_ENABLED=1`, `NEXT_PUBLIC_MKA_AUDIENCE_MOCK` unset).

```bash
apps/e2e/mka/stack.sh up            # Docker Postgres:5443 + Redis:6389, API :8043, web :3043; writes /private/tmp/claude-501/mka-e2e-stack.json
cd apps/e2e && bunx playwright test -c mka/playwright.config.ts
apps/e2e/mka/stack.sh down [--purge]
```

Global setup seeds synthetic personas (`<slug>@e2e-tests.com`, password `E2ePersona!234`, attributes via the real admin
override endpoint), the fixture course, makes `course-author@e2e-tests.com` an ACTIVE CREATOR of it (plain user role),
and logs each persona in once (storageState under the stack state dir). Admin login: `admin@e2e-tests.com`, password in
`<stateDir>/secrets.env`. Persona/course ids: `<stateDir>/personas.json`. Specs skip when no stack JSON exists.
Findings pinned as expected-failures: `docs/screens/audience/e2e/FINDINGS.md`.
