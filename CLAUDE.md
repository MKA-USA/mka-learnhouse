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
