import { describe, expect, test } from "bun:test";
import { PgDialect } from "drizzle-orm/pg-core";
import { SafetyError, TARGETS, assertCycleFileTarget, assertTokenTarget, buildCycleCourses, dbMapStore, resolveTarget, writeConfirmed, courseMap, type MapRow } from "../src";

const PROD = TARGETS.prod.host;

describe("target selection", () => {
  test("dev is the default and uses the staging host", () => {
    const t = resolveTarget();
    expect(t).toEqual({ name: "dev", host: "ilm-dev.mkausa.org", apiBase: "https://ilm-dev.mkausa.org/api/v1", orgSlug: "default" });
    expect(resolveTarget({ target: "dev" }).name).toBe("dev");
  });
  test("prod is refused without the exact prod hostname (from config), whatever else is passed", () => {
    for (const confirmProd of [undefined, "", "true", "prod", "ilm-dev.mkausa.org", `${PROD}.evil.com`, `https://${PROD}`, PROD.toUpperCase()])
      expect(() => resolveTarget({ target: "prod", confirmProd })).toThrow(SafetyError);
    expect(() => resolveTarget({ target: "prod", confirmProd: PROD })).not.toThrow();
    expect(resolveTarget({ target: "prod", confirmProd: PROD })).toEqual({ name: "prod", host: "ilm.mkausa.org", apiBase: "https://ilm.mkausa.org/api/v1", orgSlug: "default" });
  });
  test("unknown targets are refused", () => {
    expect(() => resolveTarget({ target: "staging" })).toThrow(SafetyError);
    expect(() => resolveTarget({ target: "PROD", confirmProd: PROD })).toThrow(SafetyError);
  });
  test("LH_API_BASE is checked for dev; prod always uses the configured host and ignores it", () => {
    expect(() => resolveTarget({ target: "dev", env: { LH_API_BASE: "https://ilm.mkausa.org/api/v1" } })).toThrow(SafetyError);
    expect(() => resolveTarget({ target: "dev", env: { LH_API_BASE: "http://ilm-dev.mkausa.org/api/v1" } })).toThrow(SafetyError);
    expect(() => resolveTarget({ target: "dev", env: { LH_API_BASE: "https://ilm-dev.mkausa.org/api/v1" } })).not.toThrow();
    // the .env value is the dev URL; it must neither block nor redirect a prod run
    expect(resolveTarget({ target: "prod", confirmProd: PROD, env: { LH_API_BASE: "https://ilm-dev.mkausa.org/api/v1" } }).apiBase).toBe("https://ilm.mkausa.org/api/v1");
  });
  test("the token must come from the same target's wrapper", () => {
    const dev = resolveTarget(); const prod = resolveTarget({ target: "prod", confirmProd: PROD });
    expect(() => assertTokenTarget(dev, { LH_API_TOKEN: "x", LH_TOKEN_TARGET: "prod" })).toThrow(SafetyError);
    expect(() => assertTokenTarget(prod, { LH_API_TOKEN: "x", LH_TOKEN_TARGET: "dev" })).toThrow(SafetyError);
    expect(() => assertTokenTarget(prod, { LH_API_TOKEN: "x" })).toThrow(SafetyError); // a token of unknown origin is never used
    expect(() => assertTokenTarget(dev, { LH_API_TOKEN: "x" })).toThrow(SafetyError);  // ... for dev either: no LH_TOKEN_TARGET, no go
    expect(() => assertTokenTarget(dev, { LH_API_TOKEN: "x", LH_TOKEN_TARGET: "" })).toThrow(SafetyError);
    expect(() => assertTokenTarget(prod, { LH_API_TOKEN: "x", LH_TOKEN_TARGET: "prod" })).not.toThrow();
    expect(() => assertTokenTarget(dev, { LH_API_TOKEN: "x", LH_TOKEN_TARGET: "dev" })).not.toThrow();
    expect(() => assertTokenTarget(prod, {})).not.toThrow(); // dry paths without a token
  });
  test("write gate: dev needs --confirm-staging; prod needs an explicit --write on top of --confirm-prod (which only selects the target)", () => {
    const dev = resolveTarget(); const prod = resolveTarget({ target: "prod", confirmProd: PROD });
    expect(writeConfirmed(dev, false)).toBe(false); expect(writeConfirmed(dev, true)).toBe(true); expect(writeConfirmed(dev, false, true)).toBe(false);
    expect(writeConfirmed(prod, false, false)).toBe(false); expect(writeConfirmed(prod, true, false)).toBe(false); expect(writeConfirmed(prod, false, true)).toBe(true);
    expect(() => resolveTarget({ target: "prod" })).toThrow(SafetyError);
  });
  test("org slug comes from the target config", () => {
    expect(resolveTarget().orgSlug).toBe(TARGETS.dev.orgSlug); expect(resolveTarget({ target: "prod", confirmProd: PROD }).orgSlug).toBe(TARGETS.prod.orgSlug);
  });
  test("keychain items are separate per target", () => {
    expect(TARGETS.dev.tokenItem).toBe("MKA_LH_DEV_API_TOKEN"); expect(TARGETS.prod.tokenItem).toBe("MKA_LH_PROD_API_TOKEN");
  });
});

describe("cycle-courses.json carries its target", () => {
  const dev = resolveTarget(); const prod = resolveTarget({ target: "prod", confirmProd: PROD });
  const row: MapRow = { cycleId: 1, kind: "general", departmentSlug: "", lhCourseUuid: "course_g", lhCourseId: 1, contentHash: null, structure: { courseId: 1, metaHash: "m", chapters: {}, activities: {} } };
  test("the export records target and host", () => {
    expect(buildCycleCourses("2026-27", "2026-11-01", "2026-12-01", [row], new Date(0), prod)).toMatchObject({ target: "prod", host: "ilm.mkausa.org" });
    expect(buildCycleCourses("2026-27", "2026-11-01", "2026-12-01", [row], new Date(0), dev)).toMatchObject({ target: "dev", host: "ilm-dev.mkausa.org" });
  });
  test("push-cycle refuses a file from another target, a host mismatch, and (for prod) a file without a target", () => {
    const devFile = buildCycleCourses("2026-27", "2026-11-01", "2026-12-01", [row], new Date(0), dev);
    const prodFile = buildCycleCourses("2026-27", "2026-11-01", "2026-12-01", [row], new Date(0), prod);
    expect(() => assertCycleFileTarget(devFile, prod)).toThrow(SafetyError);
    expect(() => assertCycleFileTarget(prodFile, dev)).toThrow(SafetyError);
    expect(() => assertCycleFileTarget({ target: "prod", host: "ilm-dev.mkausa.org" }, prod)).toThrow(SafetyError);
    expect(() => assertCycleFileTarget({}, prod)).toThrow(SafetyError);
    expect(() => assertCycleFileTarget(devFile, dev)).not.toThrow(); expect(() => assertCycleFileTarget(prodFile, prod)).not.toThrow();
    expect(() => assertCycleFileTarget({}, dev)).not.toThrow(); // a legacy dev file
  });
});

/** A fake db that honours the drizzle where-params of dbMapStore (target, cycle, kind, department) over an in-memory table. */
function fakeDb(rows: Record<string, unknown>[]) {
  const dialect = new PgDialect(); const inserted: Record<string, unknown>[] = []; const conflicts: unknown[] = [];
  const db = {
    select: () => ({ from: () => ({ where: (w: never) => { const p = dialect.sqlToQuery(w).params as unknown[];
      return Promise.resolve(rows.filter((r) => r.target === p[0] && r.cycleId === p[1] && r.kind === p[2] && r.departmentSlug === p[3])); } }) }),
    insert: () => ({ values: (v: Record<string, unknown>) => { inserted.push(v); return { onConflictDoUpdate: (o: unknown) => { conflicts.push(o); return Promise.resolve(); } }; } }),
  };
  return { db: db as never, inserted, conflicts };
}

describe("course_map isolation between targets", () => {
  const devRow = { target: "dev", cycleId: 1, kind: "department", departmentSlug: "tabligh", lhCourseUuid: "course_dev", lhCourseId: 9, structure: { courseId: 9, metaHash: "m", chapters: {}, activities: {} }, contentHash: null };
  test("an existing dev mapping is never returned to a prod run, and vice versa", async () => {
    const { db } = fakeDb([devRow]);
    expect((await dbMapStore(db, 1, "dev").get("department", "tabligh"))?.lhCourseUuid).toBe("course_dev");
    expect(await dbMapStore(db, 1, "prod").get("department", "tabligh")).toBeNull();
    const { db: db2 } = fakeDb([{ ...devRow, target: "prod", lhCourseUuid: "course_prod" }]);
    expect(await dbMapStore(db2, 1, "dev").get("department", "tabligh")).toBeNull();
    expect((await dbMapStore(db2, 1, "prod").get("department", "tabligh"))?.lhCourseUuid).toBe("course_prod");
  });
  test("the store defaults to dev (existing rows are target=dev)", async () => {
    const { db } = fakeDb([devRow]);
    expect((await dbMapStore(db, 1).get("department", "tabligh"))?.lhCourseUuid).toBe("course_dev");
  });
  test("saves are written with the run's target and upsert on a key that includes the target", async () => {
    const { db, inserted, conflicts } = fakeDb([]);
    const row: Omit<MapRow, "cycleId"> = { kind: "department", departmentSlug: "tabligh", lhCourseUuid: "course_p", lhCourseId: 1, structure: { courseId: 1, metaHash: "m", chapters: {}, activities: {} }, contentHash: null };
    await dbMapStore(db, 1, "prod").save(row); await dbMapStore(db, 1, "dev").save(row);
    expect(inserted.map((v) => v.target)).toEqual(["prod", "dev"]);
    expect((conflicts[0] as { target: unknown[] }).target[0]).toBe(courseMap.target);
  });
});
