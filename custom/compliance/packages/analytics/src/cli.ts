/**
 * bun run sync -- --fixtures [--date YYYY-MM-DD] [--days N]   simulate LearnHouse from the synthetic world, write snapshots (memory, prints summary)
 * Live mode (reads staging via core's LH client) needs DATABASE_URL + LH_* env and is run through scripts/with-lh-token.sh.
 */
import { aggregate } from "./aggregate";
import { attention } from "./attention";
import { addDays } from "./dates";
import { FIXTURE_CYCLE, generateWorld, expectedContacts } from "./fixtures";
import { memoryStore, runSnapshotSync } from "./sync";
import { createFixturePort, fixtureCourses } from "./sync-adapters";

const args = process.argv.slice(2);
const flag = (n: string) => { const i = args.indexOf(`--${n}`); return i < 0 ? undefined : (args[i + 1] ?? "true"); };

if (flag("fixtures")) {
  const date = flag("date") && flag("date") !== "true" ? flag("date")! : "2026-11-18";
  const days = Number(flag("days") ?? 3);
  const world = generateWorld();
  const { store, snapshots, runs } = memoryStore();
  for (let i = days - 1; i >= 0; i--) {
    const d = addDays(date, -i);
    const t0 = Date.now();
    await runSnapshotSync({ cycle: { id: 1, ...FIXTURE_CYCLE }, roster: world.roster, courses: fixtureCourses(), port: createFixturePort(world, d), store, today: d, expectedContacts, source: "fixtures" });
    console.log(`${d}: ${snapshots.get(`1:${d}`)?.length} rows in ${Date.now() - t0}ms`);
  }
  const rows = snapshots.get(`1:${date}`)!;
  const a = aggregate("all", rows, FIXTURE_CYCLE);
  console.log(JSON.stringify({ runs: runs.length, attestedPct: a.attestedPct, overdue: a.overdue, rag: attention(a, FIXTURE_CYCLE, date).rag }));
} else {
  console.error("live sync: not wired to a CLI in this workstream (see src/sync.ts runSnapshotSync + lhPortFromApi); use --fixtures");
  process.exit(2);
}
