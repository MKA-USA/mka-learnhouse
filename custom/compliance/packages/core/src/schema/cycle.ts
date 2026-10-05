import { pgTable, serial, text, date, timestamp } from "drizzle-orm/pg-core";

/** A compliance cycle, e.g. label "2026-27", running Nov 1 to deadline_on. */
export const cycle = pgTable("cycle", {
  id: serial("id").primaryKey(),
  label: text("label").notNull().unique(),
  startsOn: date("starts_on", { mode: "string" }).notNull(),
  deadlineOn: date("deadline_on", { mode: "string" }).notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});
