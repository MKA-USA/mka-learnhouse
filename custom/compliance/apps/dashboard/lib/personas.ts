import type { ViewerAttributes } from "@mka/analytics/scope";

/** Dev-only personas for fixture mode (never available in production builds). */
export interface Persona { key: string; label: string; email: string; isAdmin?: boolean; attributes: ViewerAttributes | null }
const a = (p: Partial<ViewerAttributes>): ViewerAttributes => ({ status: "matched", is_officeholder: true, level: "national", department: null, role: null, majlis: null, region: null, ...p });

export const PERSONAS: Persona[] = [
  { key: "admin", label: "Org admin (everything)", email: "admin@example.invalid", isAdmin: true, attributes: null },
  { key: "motamid", label: "Motamid (everything)", email: "motamid@example.invalid", attributes: a({ role: "motamid" }) },
  { key: "mohtamim-tarbiyyat", label: "Mohtamim Tarbiyyat", email: "tarbiyyat@example.invalid", attributes: a({ role: "mohtamim", department: "tarbiyyat" }) },
  { key: "mohtamim-tajneed", label: "Mohtamim Tajneed", email: "tajneed@example.invalid", attributes: a({ role: "mohtamim", department: "tajneed" }) },
  { key: "regional-gulf", label: "Regional Qaid Gulf", email: "rqaid.gulf@example.invalid", attributes: a({ level: "regional", role: "regional_qaid", region: "Gulf" }) },
  { key: "majlis-albany", label: "Qaid Albany", email: "qaid.albany@example.invalid", attributes: a({ level: "local", role: "qaid", majlis: "Albany", region: "Northeast" }) },
  { key: "nazim-albany", label: "Nazim Tabligh Albany (no access)", email: "tabligh.albany@example.invalid", attributes: a({ level: "local", role: "nazim_dept", department: "tabligh", majlis: "Albany", region: "Northeast" }) },
  { key: "unknown", label: "Unrecognised account (no access)", email: "someone@example.invalid", attributes: null },
];
export const personaByKey = (k: string | undefined) => PERSONAS.find((p) => p.key === k);
