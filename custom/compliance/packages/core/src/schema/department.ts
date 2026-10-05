import { pgTable, text, integer, boolean, timestamp } from "drizzle-orm/pg-core";

export const LEVELS = ["national", "region", "majlis"] as const;
export type Level = (typeof LEVELS)[number];

/** Canonical department list (mirrors the fork identity rules; versioned). */
export const department = pgTable("department", {
  slug: text("slug").primaryKey(),
  name: text("name").notNull(),
  translation: text("translation").notNull(),
  /** Mailbox local-part prefix used by the email formula (Aitmad -> motamid). */
  mailboxPrefix: text("mailbox_prefix").notNull(),
  /** Levels at which this department has officeholders. */
  levelScope: text("level_scope").array().notNull().default(["national", "region", "majlis"]),
  /** false = excluded for the cycle (config.ts DEFAULT_EXCLUDED_DEPARTMENTS): kept as a canonical department, but no course/roster. */
  active: boolean("active").notNull().default(true),
  sortOrder: integer("sort_order").notNull().default(0),
  rulesVersion: text("rules_version").notNull().default("2026.1"),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});
