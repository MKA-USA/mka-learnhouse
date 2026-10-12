# Learnhouse — Claude Code Instructions

## Codebase Knowledge Graph (MANDATORY)

The codebase-memory-mcp is the **primary source of truth** for understanding this codebase. You MUST use it before making any code changes.

### Before ANY code modification:

1. **Search the graph first** — use `mcp__codebase-memory-mcp__search_graph` to find relevant functions, classes, routes, and variables BEFORE using grep or glob.
2. **Trace dependencies** — use `mcp__codebase-memory-mcp__trace_path` to understand callers/callees and data flow before changing any function signature or behavior.
3. **Get code snippets** — use `mcp__codebase-memory-mcp__get_code_snippet` to read implementations with full graph context (not just raw file reads).
4. **Check architecture** — use `mcp__codebase-memory-mcp__get_architecture` when starting work on an unfamiliar area.

### Workflow for every change:

```
1. search_graph → find the symbol/function/route
2. trace_path (calls) → understand who calls it and what it calls
3. get_code_snippet → read the implementation with context
4. Make the change
5. trace_path (data_flow) → verify no downstream breakage
```

### Why this matters:

- The knowledge graph has full type-aware call resolution across all 1130+ source files
- It catches cross-file dependencies that grep misses
- It prevents breaking callers you didn't know existed
- Every session starts with this graph available — use it

## Project Overview

- **Monorepo** with apps: `web` (Next.js), `cli`, `collab`, `e2e`
- **Package manager**: Bun 1.4.2
- **Main app**: `apps/web` — Next.js with Turbopack
- **Testing**: `bun test tests`
- **Linting**: `eslint` (strict mode available via `lint:strict`)

## Key Commands

| Task | Command |
|------|---------|
| Dev server | `bun run dev` (in apps/web) |
| Build | `bun run build` (in apps/web) |
| Tests | `bun test tests` |
| Lint | `bun run lint:strict` |

## Session-Start: Verify Graph Freshness (MANDATORY)

At the start of EVERY session, before any code work:

1. Call `mcp__codebase-memory-mcp__index_status` for project `Users-mamjed-Documents-GitHub-mka-learnhouse`
2. Compare the indexed file count against `git log --oneline -1 --format="%H %ci"` to check if the graph covers recent commits
3. If the graph is stale (missing recent changes), re-index immediately:
   ```
   mcp__codebase-memory-mcp__index_repository(
     repo_path="/Users/mamjed/Documents/GitHub/mka-learnhouse",
     mode="full",
     persistence=true
   )
   ```
4. Only then proceed with the task

## Rebuild Policy

- **Every agent session**: check freshness via `index_status` before coding
- **After `git pull`**: re-index if significant changes were pulled
- **After merging a PR**: re-index to capture new code
- **Persistent artifact**: `.codebase-memory/graph.db.zst` is committed so teammates bootstrap from it instead of full re-indexing
- **Manual rebuild**: ask "rebuild the codebase graph" or run `scripts/rebuild-codebase-graph.sh`

## Upstream Fork Policy (CRITICAL)

This project is a fork of an open-source tool. **Never modify upstream files in ways that would break our ability to pull new releases.**

### Before ANY file modification:

1. **Check if the file is upstream-owned** — use `git log --follow -- <file>` to see if it exists in upstream history
2. **Classify the change** using the fork-safety decision framework:
   - **Safe**: New files, config files, agent instructions, custom extensions in isolated directories
   - **Risky**: Modifications to upstream source files — requires explicit approval
   - **Blocked**: Changes that would cause merge conflicts with upstream — find an extension point instead

3. **If modifying an upstream file is unavoidable**:
   - Document the change in `.codebase-memory/upstream-modifications.md`
   - Explain why no extension point exists
   - Provide the exact diff so it can be re-applied after pulling upstream

### Fork-Safe Design Patterns:

- **Extension points**: Use hooks, plugins, or wrapper modules instead of modifying core files
- **Separation**: Custom features go in clearly separated directories (e.g., `custom/`, `extensions/`)
- **Configuration over code**: Prefer config changes over code modifications
- **Override patterns**: Use inheritance, composition, or dependency injection to extend behavior

### Jev Fork-Safety Check (Optional):

If Jev/TypeSafe is available, classify changes before implementing:

```python
# Example Jev classification for fork safety
state = {
    "file_path": "apps/web/services/payments/stripe.ts",
    "change_description": "Adding custom payment gateway integration",
    "is_upstream_file": True,
    "change_type": "feature_addition"
}

questions = {
    "would_break_pull": {
        "type": "noul",
        "instructions": "Would this change cause merge conflicts when pulling upstream updates?",
        "criteria": {
            "true": "modifies core logic, changes function signatures, alters imports",
            "false": "adds new files, extends via config, uses extension points"
        }
    },
    "change_category": {
        "type": "choice",
        "instructions": "What category does this change fall into?",
        "criteria": {
            "safe_extension": "new file, custom extension, isolated feature",
            "upstream_modification": "modifies existing upstream file",
            "config_only": "configuration, environment, documentation",
            "blocked": "would break pullability, needs redesign"
        }
    }
}
```

**When in doubt, ask the user before modifying upstream files.**

## Skills

### Learnhouse Course Builder

When asked to create a course, generate course content, build quizzes/assignments, or deploy learning material, **read `.claude/skills/learnhouse-course-builder/SKILL.md` first**.

This skill documents:
- The complete course architecture (Course → Chapter → Activity → Block)
- All 6 AI generation APIs (course planning, content generation, quiz generation, assignment generation, scenario generation, MagicBlocks)
- ProseMirror JSON format and all available block types
- The end-to-end workflow: plan → generate content → add assessments → publish
- MKA Ilm brand considerations for content generation

Key APIs available:
- `POST /ai/courseplanning/start` — Generate course structure from a topic
- `POST /ai/courseplanning/finalize` — Create course/chapters/activities in DB
- `POST /ai/courseplanning/generate-activity` — Generate ProseMirror content
- `POST /ai/quiz/generate` — Generate inline quiz questions
- `POST /ai/assignments/generate` — Generate graded assignments (QUIZ, FORM, SHORT_ANSWER, NUMBER_ANSWER, FILE_SUBMISSION)
- `POST /ai/scenario/generate` — Generate branching decision scenarios

## Agent skills

### Issue tracker

GitHub Issues on `MKA-USA/mka-learnhouse` (the fork, never `learnhouse/learnhouse`), via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Syncing upstream

- **Cadence:** `.github/workflows/mka-upstream-sync.yaml` runs Mon+Thu 14:00 UTC (and on demand: `gh workflow run mka-upstream-sync.yaml`). It merges `learnhouse/learnhouse` `dev` into a `sync/upstream-YYYY-MM-DD` branch and opens a PR into `dev`. PR-body/gating logic: `scripts/mka/upstream-sync-report.py`.
- **Labels:** `upstream-sync` = automated sync PR. `needs-review` = carries migrations, config/env changes, workflow changes, or fork hook sites; auto-merge is off, review before merging. `ai-resolved` = Claude resolved conflicts (prompt: `.github/mka/upstream-conflict-prompt.md`); never auto-merged, read its resolution summary. `ready-for-agent` on the issue "Upstream sync blocked by conflicts" = the bot gave up; resolve by hand.
- **Merge commits only.** Sync PRs and dev->prod use "Create a merge commit". Never squash/rebase a sync: it destroys the merge-base and the next sync re-conflicts on every file.
- **rerere:** `git config rerere.enabled true` locally so repeated conflicts reuse earlier resolutions (the workflow's cache does not persist between runs).
- **Resolve a blocked issue manually:** fetch `upstream`, branch `sync/upstream-manual` from `origin/dev`, run `git merge --no-ff upstream/dev`; take upstream as base and re-apply fork hooks per `.codebase-memory/upstream-modifications.md`; regenerate lockfiles (`cd apps/api && uv lock`, `cd apps/web && bun install`) instead of hand-merging; run api tests + web lint/typecheck; commit, push, open a PR into `dev` labeled `upstream-sync`, merge with a merge commit. Update `upstream-modifications.md` if a hook moved.
- **Keep the fork footprint small.** Prefer new `mka-` files and extension points over editing upstream files; every upstream-file edit is a future conflict and must be logged in `upstream-modifications.md`. Never edit upstream workflows (use `gh workflow disable`).
- **Secrets/settings:** `MKA_SYNC_APP_ID`, `MKA_SYNC_APP_PRIVATE_KEY`, `ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN`). Rulesets in `.github/mka/rulesets/`; the single required check is `MKA CI gate` (`mka-ci-gate.yaml`).
