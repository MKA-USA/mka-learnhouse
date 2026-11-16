#!/usr/bin/env bun
import { parseArgs } from "./args";
import { cmdApply, cmdExportCourses, cmdPlan, cmdPublish, cmdReconcile } from "./commands-lh";
import { cmdAssignAuthors, cmdIdentityStatus, cmdPushCycle, cmdPushRoster, cmdSyncIdentity } from "./commands-push";
import { cmdGapReport, cmdImport, cmdRoster, cmdSeedThinkific } from "./commands-data";
import { TARGET_COMMANDS, initTarget } from "./target";

const a = parseArgs(process.argv.slice(2));
const cmd = a.pos[0];
const USAGE = `provisioner <command>
  roster [--cycle 2026-27]                      generate roster from the email formula (idempotent)
  import <dept-plans|overrides|names> <csv> [--cycle]
  seed-thinkific [--dir <data>]                 seed stale 2025-26 plans from the Thinkific export
  plan [--pilot|--only a,b|--all]                dry run (default; writes nothing)
  apply --confirm-staging --pilot|--only|--all [--from-cycle 2025-26]   create/update DRAFT courses on staging only (author pages seeded once; removes activities that left the spec)
  reconcile --pilot|--only|--all [--apply --confirm-staging]   enroll EXISTING users only (dry run default)
  publish --course <name|uuid>|--all [--execute --confirm-staging]   publishes course+activities; DRY RUN by default
  export-courses [--cycle]                       writes out/cycle-courses.json
  push-cycle [--apply --confirm-staging] [--starts-on --deadline-on]   -> fork POST /mka/compliance/cycles
  push-roster --all|--pilot|--only [--apply --confirm-staging] [--batch-size N]   -> POST /mka/compliance/expected/import
  assign-authors --map mohtamims.csv [--apply --confirm-staging]
  sync-identity [--dry-run (default) | --apply --confirm-staging]   -> POST /mka/identity/sync (Mohtamim role + groups backfill)
  identity-status                               -> GET /mka/identity/status
  gap-report [--cycle] [--data <dir>] [--carry-over 2025-26]
  (LearnHouse commands) --target dev|prod   default dev. prod needs --confirm-prod <exact prod hostname> for ANY use and the token from \`bun run lh:prod\`
                                               (keychain MKA_LH_PROD_API_TOKEN); course_map, idmap, enrollment_log and out/ are separate per target; writes on prod use --confirm-prod instead of --confirm-staging
  (any command) --include-atfal   Atfal is excluded by default (core config); this switches it back on`;
try {
  if (cmd && TARGET_COMMANDS.has(cmd)) initTarget(a);
  switch (cmd) {
    case "roster": await cmdRoster(a); break;
    case "import": await cmdImport(a); break;
    case "seed-thinkific": await cmdSeedThinkific(a); break;
    case "plan": await cmdPlan(a); break;
    case "reconcile": await cmdReconcile(a); break;
    case "publish": await cmdPublish(a); break;
    case "export-courses": await cmdExportCourses(a); break;
    case "push-cycle": await cmdPushCycle(a); break;
    case "push-roster": await cmdPushRoster(a); break;
    case "assign-authors": await cmdAssignAuthors(a); break;
    case "sync-identity": await cmdSyncIdentity(a); break;
    case "identity-status": await cmdIdentityStatus(a); break;
    case "apply": await cmdApply(a); break;
    case "gap-report": await cmdGapReport(a); break;
    default: console.log(USAGE);
  }
} catch (e) { console.error((e as Error).message); process.exit(1); }
