import { mock } from "bun:test";
import { personaByKey } from "@/lib/personas";

/** Make `getViewer()` return the given persona (or nobody). Call before importing a route handler or lib/access. */
export function actAs(key: string | null) {
  mock.module("@/lib/viewer", () => ({
    getViewer: async () => { const p = key ? personaByKey(key) : null; return p ? { email: p.email, name: p.label, devPersona: p.key } : null; },
  }));
}
