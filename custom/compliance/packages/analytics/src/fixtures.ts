/**
 * Deterministic synthetic world (~1,175 officeholders x 2 courses) so the dashboard and sync can be demoed
 * before real data exists. All identities are synthetic (`@example.invalid`). Same seed => same world.
 */
import { DEPARTMENTS } from "../../core/src/seed/departments";
import { addDays, diffDays, maxDay } from "./dates";
import { evaluateSelfCheck } from "./selfcheck";
import { scoreLearner, windowStart } from "./status";
import { withConfig, type AttentionConfig, type DeepPartial } from "./config";
import type { CourseProgress, CycleInfo, LearnerRecord, RosterEntry, ScoredLearner } from "./types";

/** Majlis -> Region, mirrors the fork's MAJLIS_TO_REGION (apps/api services/users/mka_profile.py). Org structure, not PII. */
export const MAJLIS_TO_REGION: Record<string, string> = {
  Baltimore: "East", "Central Jersey": "East", Harrisburg: "East", "North Jersey": "East", Philadelphia: "East", Willingboro: "East",
  Cleveland: "Great Lakes", Columbus: "Great Lakes", Dayton: "Great Lakes", Detroit: "Great Lakes", Indiana: "Great Lakes", Kentucky: "Great Lakes",
  Austin: "Gulf", Dallas: "Gulf", "Fort Worth": "Gulf", Houston: "Gulf", Tulsa: "Gulf",
  Chicago: "Midwest", "Kansas City": "Midwest", Milwaukee: "Midwest", Minnesota: "Midwest", Oshkosh: "Midwest", "Saint Louis": "Midwest", Zion: "Midwest",
  Muqami: "Muqami",
  Bronx: "New York Metro", Brooklyn: "New York Metro", "Long Island": "New York Metro", Queens: "New York Metro",
  Albany: "Northeast", Boston: "Northeast", Connecticut: "Northeast", Rochester: "Northeast", "Syracuse-Binghamton": "Northeast",
  "Bay Point": "Northwest", Portland: "Northwest", Sacramento: "Northwest", Seattle: "Northwest", "Silicon Valley": "Northwest",
  Atlanta: "Southeast", Charlotte: "Southeast", Miami: "Southeast", Orlando: "Southeast", Tennessee: "Southeast",
  "Las Vegas": "Southwest", "Los Angeles": "Southwest", Phoenix: "Southwest", Tucson: "Southwest",
  "North Virginia": "Virginia", "South Virginia": "Virginia", Richmond: "Virginia", RTP: "Virginia",
};

export const FIXTURE_CYCLE: CycleInfo = { label: "2026-27", startsOn: "2026-11-01", deadlineOn: "2026-12-01" };
export const GENERAL_LESSONS = 7;
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");
/** Synthetic mailbox prefix: unique per department (the real Nau Mubaeen/Rishta Nata reuse is a core/fork concern, not simulated here). */
const mb = slug;

// ---- deterministic randomness ------------------------------------------------
function hash(s: string): number { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
function rng(seed: number) { let a = seed >>> 0; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

// ---- department behaviour profiles (the deliberate problems) ------------------
interface Profile { neverStart: number; pace: [number, number]; startDelay: number; stall: number; noAttest: number; mismatch: number }
const BASE: Profile = { neverStart: 0.05, pace: [0.6, 1.6], startDelay: 12, stall: 0.05, noAttest: 0.06, mismatch: 0.04 };
const PROFILES: Record<string, Partial<Profile>> = {
  tarbiyyat: { neverStart: 0.55, startDelay: 20 },          // problem: most haven't started
  "waqf-e-nau": { stall: 0.6 },                              // problem: stuck partway
  ishaat: { mismatch: 0.3 },                                 // problem: contact data wrong
  "new-immigrants": { noAttest: 0.5 },                       // problem: finish but never sign off
  tajneed: { neverStart: 0.01, pace: [1.5, 2.5], startDelay: 3, noAttest: 0.01 },
  taleem: { neverStart: 0.01, pace: [1.4, 2.4], startDelay: 4, noAttest: 0.02 },
};
const REGION_FIX: { dept: string; regions: string[]; neverStart: number }[] = [
  { dept: "maal", regions: ["Gulf", "Southwest"], neverStart: 0.85 },   // problem: department x region cell
];

interface Trajectory {
  startAbs: string | null; pace: number; cap: number;      // cap = max lessons ever reached (stall)
  deptLessons: number; attestsGeneral: boolean; attestsDept: boolean; lagGeneral: number; lagDept: number;
  quizBase: number; wrongField: string | null;
}

export interface FixtureWorld {
  cycle: CycleInfo; seed: number; roster: RosterEntry[];
  traj: Map<string, Trajectory>;
}

export function generateRoster(): RosterEntry[] {
  const out: RosterEntry[] = [];
  const regions = [...new Set(Object.values(MAJLIS_TO_REGION))].sort();
  for (const d of DEPARTMENTS) out.push({ id: `nat:${d.slug}`, departmentSlug: d.slug, level: "national", region: "", majlis: "", roleTitle: `Mohtamim ${d.name}`, email: `${mb(d.slug)}@example.invalid`, personName: `Synthetic Mohtamim ${d.name}` });
  for (const r of regions) out.push({ id: `reg:${slug(r)}`, departmentSlug: "", level: "region", region: r, majlis: "", roleTitle: "Regional Qaid", email: `rqaid.${slug(r)}@example.invalid`, personName: `Synthetic Qaid ${r}` });
  for (const [m, r] of Object.entries(MAJLIS_TO_REGION).sort()) {
    out.push({ id: `maj:${slug(m)}:qaid`, departmentSlug: "", level: "majlis", region: r, majlis: m, roleTitle: "Qaid", email: `qaid.${slug(m)}@example.invalid`, personName: `Synthetic Qaid ${m}` });
    for (const d of DEPARTMENTS) out.push({ id: `maj:${slug(m)}:${d.slug}`, departmentSlug: d.slug, level: "majlis", region: r, majlis: m, roleTitle: `Nazim ${d.name}`, email: `${mb(d.slug)}.${slug(m)}@example.invalid`, personName: `Synthetic Nazim ${d.name} ${m}` });
  }
  return out;
}

export function generateWorld(opts: { seed?: number; cycle?: CycleInfo } = {}): FixtureWorld {
  const seed = opts.seed ?? 20261101, cycle = opts.cycle ?? FIXTURE_CYCLE;
  const roster = generateRoster();
  const traj = new Map<string, Trajectory>();
  for (const e of roster) {
    const r = rng(hash(`${seed}:${e.id}`));
    // ~3% of local officeholders are mid-year appointees
    if (e.level === "majlis" && e.departmentSlug && r() < 0.03) e.appointedOn = addDays(cycle.startsOn, 5 + Math.floor(r() * 15));
    const p: Profile = { ...BASE, ...(PROFILES[e.departmentSlug] ?? {}) };
    for (const fx of REGION_FIX) if (fx.dept === e.departmentSlug && fx.regions.includes(e.region)) p.neverStart = fx.neverStart;
    const never = r() < p.neverStart;
    const deptLessons = e.departmentSlug ? 5 + (hash(e.departmentSlug) % 4) : 0;
    const total = GENERAL_LESSONS + deptLessons;
    const start = windowStart(e, cycle);
    const startAbs = never ? null : addDays(start, Math.floor(r() * p.startDelay));
    const pace = p.pace[0] + r() * (p.pace[1] - p.pace[0]);
    const stalled = r() < p.stall;
    const cap = stalled ? Math.max(1, Math.floor(total * (0.35 + r() * 0.4))) : total;
    const wrongField = r() < p.mismatch ? (r() < 0.5 ? "regionalQaid" : "deptHead") : null;
    traj.set(e.id, {
      startAbs, pace, cap, deptLessons,
      attestsGeneral: r() >= p.noAttest * 0.5, attestsDept: r() >= p.noAttest,
      lagGeneral: Math.floor(r() * 2), lagDept: Math.floor(r() * 4),
      quizBase: 55 + Math.floor(r() * 45), wrongField,
    });
  }
  return { cycle, seed, roster, traj };
}

/** Day on which lesson j (1-based) is done. */
const lessonDay = (startAbs: string, pace: number, j: number) => addDays(startAbs, Math.ceil((j - 1) / pace));
const lessonsDoneBy = (t: Trajectory, day: string, total: number): number => {
  if (!t.startAbs || diffDays(day, t.startAbs) < 0) return 0;
  return Math.min(t.cap, total, Math.floor(diffDays(day, t.startAbs) * t.pace) + 1);
};

export function expectedContacts(e: RosterEntry) {
  const d = DEPARTMENTS.find((x) => x.slug === e.departmentSlug);
  return { majlis: e.majlis || undefined, regionalQaid: e.region ? `rqaid.${slug(e.region)}@example.invalid` : undefined, deptHead: d ? `${mb(d.slug)}@example.invalid` : undefined };
}

/** The learner's record as it would look in LearnHouse on `day`. */
export function recordAt(world: FixtureWorld, e: RosterEntry, day: string): LearnerRecord {
  const t = world.traj.get(e.id)!;
  const total = GENERAL_LESSONS + t.deptLessons;
  const done = lessonsDoneBy(t, day, total);
  const gDone = Math.min(done, GENERAL_LESSONS), dDone = Math.max(0, done - GENERAL_LESSONS);
  const doneAt = (j: number) => (t.startAbs ? lessonDay(t.startAbs, t.pace, j) : null);
  const gComplete = gDone >= GENERAL_LESSONS ? doneAt(GENERAL_LESSONS) : null;
  const dComplete = t.deptLessons > 0 && dDone >= t.deptLessons ? doneAt(total) : null;
  const gAtt = gComplete && t.attestsGeneral ? addDays(gComplete, t.lagGeneral) : null;
  const dAtt = dComplete && t.attestsDept ? addDays(dComplete, t.lagDept) : null;
  const gAttested = gAtt && diffDays(day, gAtt) >= 0 ? gAtt : null;
  const dAttested = dAtt && diffDays(day, dAtt) >= 0 ? dAtt : null;
  const quiz = (n: number) => Array.from({ length: Math.min(2, Math.floor(n / 4)) }, (_, i) => Math.min(100, t.quizBase + i * 7));
  const general: CourseProgress = {
    enrolled: true, lessonsDone: gDone, lessonsTotal: GENERAL_LESSONS, completedAt: gComplete, attestedAt: gAttested,
    quizScores: quiz(gDone), lastActivityAt: gDone > 0 && t.startAbs ? maxDay(doneAt(gDone), gAttested) : null,
  };
  const dept: CourseProgress | null = t.deptLessons === 0 ? null : {
    enrolled: true, lessonsDone: dDone, lessonsTotal: t.deptLessons, completedAt: dComplete, attestedAt: dAttested,
    quizScores: quiz(dDone), lastActivityAt: dDone > 0 && t.startAbs ? maxDay(doneAt(GENERAL_LESSONS + dDone), dAttested) : null,
  };
  let selfCheck;
  if (e.level === "majlis" && e.departmentSlug && dComplete && diffDays(day, dComplete) >= 0) {
    const exp = expectedContacts(e);
    const wrong = "qaid.someone-else@example.invalid";
    selfCheck = evaluateSelfCheck({
      majlis: exp.majlis, regionalQaid: t.wrongField === "regionalQaid" ? wrong : exp.regionalQaid,
      deptHead: t.wrongField === "deptHead" ? wrong : exp.deptHead,
    }, exp);
  }
  return { ...e, general, department: dept, selfCheck };
}

export function snapshotAt(world: FixtureWorld, day: string, cfg?: DeepPartial<AttentionConfig>): ScoredLearner[] {
  const c = withConfig(cfg);
  return world.roster.map((e) => scoreLearner(recordAt(world, e, day), world.cycle, day, c));
}
