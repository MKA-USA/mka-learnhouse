import { pgTable, serial, text, timestamp, unique } from "drizzle-orm/pg-core";

/** Traceability: source system ids (e.g. Thinkific) -> new LearnHouse uuids. */
export const idmap = pgTable(
  "idmap",
  {
    id: serial("id").primaryKey(),
    target: text("target").notNull().default("dev"),
    sourceSystem: text("source_system").notNull(),
    sourceKind: text("source_kind").notNull(),
    sourceId: text("source_id").notNull(),
    lhKind: text("lh_kind").notNull(),
    lhUuid: text("lh_uuid").notNull(),
    sourcePath: text("source_path"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [unique("idmap_key").on(t.target, t.sourceSystem, t.sourceKind, t.sourceId)],
);
