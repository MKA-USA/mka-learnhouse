# Dashboard + analytics (W3)

Run (demo, no Google, no DB): `cd apps/dashboard && bun install && cp .env.example .env.local && bun run dev` -> http://localhost:3100.
Fixture mode shows a "View as" persona switcher (non-production only). Synthetic world: 1,176 officeholders x 22 courses, deliberate problem departments (Tarbiyyat not started, Waqf-e-Nau stuck, Ishaat contact mismatches, New Immigrants no sign-off, Maal in Gulf/Southwest).

Checks: `cd packages/analytics && bun test && bunx tsc -p tsconfig.json`; `cd apps/dashboard && bun test && bunx tsc --noEmit && bunx eslint . && bunx next build`; `bun test packages apps` from this folder runs everything.
Sync demo: `cd packages/analytics && bun run src/cli.ts --fixtures --days 3`. Migration: `bun run db:generate` / `bun run db:migrate` (own folder `packages/analytics/drizzle`, own table `__drizzle_migrations_analytics`; run core's migrations first).

Authorization: every page, `/api/chase` (CSV) and `/api/rows` go through `lib/access.ts::loadScoped` -> `packages/analytics/src/scope.ts` (fail closed: unknown/ambiguous/partial attributes = no access; `deny` override wins). Tests: `apps/dashboard/test/authz.test.ts`, `packages/analytics/test/scope.test.ts`.

Workspace note: `packages/analytics` and `apps/dashboard` each have their own lockfile because root `package.json` workspaces (owned by W2) does not list them. Add them to `workspaces` at merge if a single install is wanted; imports use relative/tsconfig paths so nothing else changes.
