#!/usr/bin/env bun
import { parseArgs } from "./args";
import { cmdApply, cmdExportCourses, cmdPlan, cmdPublish, cmdReconcile } from "./commands-lh";
import { cmdAssignAuthors, cmdPushCycle, cmdPushRoster } from "./commands-push";
import { cmdGapReport, cmdImport, cmdRoster, cmdSeedThinkific } from "./commands-data";

const a = parseArgs(process.argv.slice(2));
const cmd = a.pos[0];
const USAGE = `provisioner <command>
  roster [--cycle 2026-27]                      generate roster from the email formula (idempotent)
  import <dept-plans|overrides|names> <csv> [--cycle]
  seed-thinkific [--dir <data>]                 seed stale 2025-26 plans from the Thinkific export
  plan [--pilot|--only a,b|--all]                dry run (default; writes nothing)
  apply --confirm-staging --pilot|--only|--all    create/update DRAFT courses on staging only
  reconcile --pilot|--only|--all [--apply --confirm-staging]   enroll EXISTING users only (dry run default)
  publish --course <name|uuid>|--all [--execute --confirm-staging]   publishes course+activities; DRY RUN by default
  export-courses [--cycle]                       writes out/cycle-courses.json
  push-cycle [--apply --confirm-staging] [--starts-on --deadline-on]   -> fork POST /mka/compliance/cycles
  push-roster --all|--pilot|--only [--apply --confirm-staging] [--batch-size N]   -> POST /mka/compliance/expected/import
  assign-authors --map mohtamims.csv [--apply --confirm-staging]
  gap-report [--cycle] [--data <dir>] [--carry-over 2025-26]
  (any command) --include-atfal   Atfal is excluded by default (core config); this switches it back on`;
try {
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
    case "apply": await cmdApply(a); break;
    case "gap-report": await cmdGapReport(a); break;
    default: console.log(USAGE);
  }
} catch (e) { console.error((e as Error).message); process.exit(1); }
