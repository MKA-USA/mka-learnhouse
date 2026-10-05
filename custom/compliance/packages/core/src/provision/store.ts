import { and, eq } from "drizzle-orm";
import type { PostgresJsDatabase } from "drizzle-orm/postgres-js";
import { courseMap, idmap } from "../schema";
import type { IdmapEntry, MapRow, MapStore } from "./types";

export function dbMapStore(db: PostgresJsDatabase<any>, cycleId: number): MapStore {
  return {
    async get(kind, departmentSlug) {
      const [r] = await db.select().from(courseMap).where(and(eq(courseMap.cycleId, cycleId), eq(courseMap.kind, kind), eq(courseMap.departmentSlug, departmentSlug)));
      return r ? ({ cycleId, kind, departmentSlug, lhCourseUuid: r.lhCourseUuid, lhCourseId: r.lhCourseId, structure: r.structure as any, contentHash: r.contentHash } as MapRow) : null;
    },
    async save(row) {
      await db.insert(courseMap).values({ cycleId, kind: row.kind, departmentSlug: row.departmentSlug, lhCourseUuid: row.lhCourseUuid, lhCourseId: row.lhCourseId, structure: row.structure as any, contentHash: row.contentHash })
        .onConflictDoUpdate({ target: [courseMap.cycleId, courseMap.kind, courseMap.departmentSlug], set: { lhCourseUuid: row.lhCourseUuid, lhCourseId: row.lhCourseId, structure: row.structure as any, contentHash: row.contentHash, updatedAt: new Date() } });
    },
    async addIdmap(e: IdmapEntry) {
      await db.insert(idmap).values({ sourceSystem: e.sourceSystem, sourceKind: e.sourceKind, sourceId: e.sourceId, lhKind: e.lhKind, lhUuid: e.lhUuid, sourcePath: e.sourcePath ?? null })
        .onConflictDoUpdate({ target: [idmap.sourceSystem, idmap.sourceKind, idmap.sourceId], set: { lhUuid: e.lhUuid, lhKind: e.lhKind, sourcePath: e.sourcePath ?? null } });
    },
  };
}
export function memoryMapStore(): MapStore & { rows: Map<string, MapRow>; idmap: IdmapEntry[] } {
  const rows = new Map<string, MapRow>(); const ids: IdmapEntry[] = [];
  return { rows, idmap: ids,
    async get(k, d) { const r = rows.get(`${k}|${d}`); return r ? structuredClone(r) : null; },
    async save(r) { rows.set(`${r.kind}|${r.departmentSlug}`, structuredClone({ cycleId: 0, ...r })); },
    async addIdmap(e) { if (!ids.some((x) => x.sourceKind === e.sourceKind && x.sourceId === e.sourceId)) ids.push(e); } };
}
