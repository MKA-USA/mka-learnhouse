import { describe, expect, test } from "bun:test";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { DEPARTMENTS } from "../src/seed/departments";

// Fork rules file (written in the attrs worktree). Override with RULES_PATH; SKIPS if absent.
const rulesPath = process.env.RULES_PATH ??
  fileURLToPath(new URL("../../../../../apps/api/src/services/mka/identity_rules/2026.1.json", import.meta.url));
const present = existsSync(rulesPath);

describe.skipIf(!present)("department table conforms to fork identity rules", () => {
  const rules = present ? JSON.parse(readFileSync(rulesPath, "utf8")) : {};
  const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  test("same 21 department names", () => {
    const a = rules.departments.map((d: { name: string }) => norm(d.name)).sort();
    expect(DEPARTMENTS.map((d) => d.slug).sort()).toEqual(a);
  });
  test("mailbox prefixes match rules (national mohtamim mailboxes + motamid for Aitmad)", () => {
    const national = rules.domains["mkausa.org"].national_exact as Record<string, { department: string | null; role: string }>;
    const byDept = new Map<string, string>();
    for (const [prefix, v] of Object.entries(national)) if (v.department && (v.role === "mohtamim" || v.role === "motamid")) byDept.set(v.department, prefix);
    for (const d of rules.departments as { key: string; name: string }[]) {
      const mine = DEPARTMENTS.find((x) => x.slug === norm(d.name))!;
      expect({ dept: d.key, prefix: mine.mailboxPrefix }).toEqual({ dept: d.key, prefix: byDept.get(d.key) as string });
    }
  });
});
