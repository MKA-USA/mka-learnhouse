import { DEPARTMENTS } from "../seed/departments";
import { ATFAL_ALIASES, MAJLIS_NAMES, MAJLIS_TO_REGION, REGION_NAMES, slugify } from "../roster/generate";

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");

const DEPT_INDEX = new Map<string, string>();
for (const d of DEPARTMENTS) for (const k of [d.slug, d.name, d.translation, d.mailboxPrefix]) DEPT_INDEX.set(norm(k), d.slug);
for (const [k, v] of Object.entries({ tarbiyat: "tarbiyyat", tahrik: "tahrik-e-jadid", tahrikejadid: "tahrik-e-jadid", immigrant: "new-immigrants", immigrants: "new-immigrants",
  generalsecretary: "aitmad", motamid: "aitmad", rishtanata: "rishta-nata", amoortuluba: "amoor-e-tuluba", sanatotijarat: "sanat-o-tijarat", sehatjismani: "sehat-e-jismani" })) DEPT_INDEX.set(k, v);

export function resolveDepartment(raw: string): string | null {
  const k = norm(raw.replace(/training course/i, ""));
  return DEPT_INDEX.get(k) ?? null;
}

const MAJLIS_INDEX = new Map<string, string>();
for (const m of MAJLIS_NAMES) MAJLIS_INDEX.set(norm(m), m);
export interface MajlisResolution { name: string | null; aliased: boolean }
export function resolveMajlis(raw: string): MajlisResolution {
  const k = norm(raw);
  const direct = MAJLIS_INDEX.get(k);
  if (direct) return { name: direct, aliased: false };
  const alias = ATFAL_ALIASES[slugify(raw)];
  if (alias) return { name: alias, aliased: true };
  return { name: null, aliased: false };
}
export function resolveRegion(raw: string): string | null {
  const k = norm(raw);
  return REGION_NAMES.find((r) => norm(r) === k) ?? null;
}
export const regionOfMajlis = (m: string) => MAJLIS_TO_REGION[m] ?? "";

/** Department implied by a role mailbox (local part before '.' on mkausa.org, 'nazim|murabbi' on atfalusa.org). */
export function departmentFromEmail(email: string): { department: string | null; majlisSlug: string | null } {
  const [local = "", domain = ""] = email.toLowerCase().split("@");
  const dot = local.indexOf(".");
  const prefix = dot < 0 ? local : local.slice(0, dot);
  const rest = dot < 0 ? null : local.slice(dot + 1);
  if (domain === "atfalusa.org") return { department: prefix === "nazim" || prefix === "murabbi" ? "atfal" : null, majlisSlug: rest };
  const d = DEPARTMENTS.find((x) => x.mailboxPrefix === prefix);
  return { department: d?.slug ?? null, majlisSlug: rest };
}
