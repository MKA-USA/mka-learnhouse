import majlisData from "../data/majlis-regions.json";
import { DEFAULT_EXCLUDED_DEPARTMENTS, activeDepartments } from "../config";

export const ROSTER_SOURCE = "formula";
/** Regional department mailboxes `{dept}.{region}@mkausa.org`: pattern CONFIRMED by the product owner (2026-10-05), so they use the plain `formula` source.
 *  UNCONFIRMED_SOURCE stays as the mechanism for any future unconfirmed pattern: rows with this source are pushed with `formula_unconfirmed: true`. */
export const UNCONFIRMED_SOURCE = "formula-unconfirmed";
export const MKA_DOMAIN = "mkausa.org";
export const ATFAL_DOMAIN = "atfalusa.org";

export interface RosterRow {
  departmentSlug: string; role: string; level: "national" | "region" | "majlis";
  region: string; majlis: string; roleTitle: string; learnerEmail: string;
  personName?: string | null; source: string; flags?: string[]; slot?: string; appointedOn?: string | null;
}

export const MAJLIS_TO_REGION: Record<string, string> = majlisData.majlis_to_region;
export const MAJLIS_NAMES = Object.keys(MAJLIS_TO_REGION);
export const REGION_NAMES = [...new Set(Object.values(MAJLIS_TO_REGION))].filter((r) => r !== "Muqami").sort();

/** Mailbox slug: lowercase, spaces removed, hyphens kept ("Saint Louis" -> "saintlouis"). */
export const slugify = (s: string) => s.toLowerCase().replace(/\s+/g, "");

/** Majlis slugs that the fork rules map to a different canonical Majlis (atfalusa.org). */
export const ATFAL_ALIASES: Record<string, string> = { syracuse: "Syracuse-Binghamton" };

const NON_DEPT_LOCAL = [
  { prefix: "qaid", role: "qaid", title: "Qaid" },
  { prefix: "naibqaid", role: "naib_qaid", title: "Naib Qaid" },
] as const;
const NATIONAL_STAFF = ["legal", "events", "it", "media", "expense"];

export interface GenerateOptions {
  /** email (lowercase) -> display name, optional enrichment */
  names?: Map<string, string>;
  /** Departments left out entirely (see config.ts). Defaults to DEFAULT_EXCLUDED_DEPARTMENTS (Atfal). */
  excludedDepartments?: readonly string[];
}

export function localRoleDefs(excluded: readonly string[] = DEFAULT_EXCLUDED_DEPARTMENTS) {
  const dept = activeDepartments(excluded).map((d) => ({
    prefix: d.mailboxPrefix, role: d.slug === "aitmad" ? "motamid" : "nazim_dept",
    departmentSlug: d.slug, title: d.slug === "aitmad" ? "Motamid" : `Nazim ${d.name}`,
    domain: MKA_DOMAIN, skip: d.slug === "atfal",
  })).filter((x) => !x.skip);
  const other = NON_DEPT_LOCAL.map((x) => ({ prefix: x.prefix, role: x.role, departmentSlug: "", title: x.title, domain: MKA_DOMAIN }));
  return [...dept, ...other];
}

/** Every Majlis has every role. Pure; no I/O. */
export function generateRoster(opts: GenerateOptions = {}): RosterRow[] {
  const rows: RosterRow[] = [];
  const excluded = opts.excludedDepartments ?? DEFAULT_EXCLUDED_DEPARTMENTS;
  const departments = activeDepartments(excluded);
  const nameOf = (email: string) => opts.names?.get(email.toLowerCase()) ?? null;
  const push = (r: Omit<RosterRow, "personName" | "source">, source = ROSTER_SOURCE) =>
    rows.push({ ...r, learnerEmail: r.learnerEmail.toLowerCase(), personName: nameOf(r.learnerEmail), source });

  // national
  for (const d of departments) {
    const isAitmad = d.slug === "aitmad";
    push({ departmentSlug: d.slug, role: isAitmad ? "motamid" : "mohtamim", level: "national", region: "", majlis: "",
      roleTitle: isAitmad ? "National Motamid" : `Mohtamim ${d.name}`, learnerEmail: `${d.mailboxPrefix}@${MKA_DOMAIN}` });
  }
  push({ departmentSlug: "", role: "sadr", level: "national", region: "", majlis: "", roleTitle: "Sadr", learnerEmail: `sadr@${MKA_DOMAIN}` });
  for (const s of NATIONAL_STAFF) push({ departmentSlug: "", role: "national_staff", level: "national", region: "", majlis: "", roleTitle: `National staff (${s})`, slot: s, learnerEmail: `${s}@${MKA_DOMAIN}` });

  // regional qaids
  for (const region of REGION_NAMES) {
    push({ departmentSlug: "", role: "regional_qaid", level: "region", region, majlis: "", roleTitle: "Regional Qaid", learnerEmail: `qaid.${slugify(region)}@${MKA_DOMAIN}` });
  }

  // regional department officeholders (pattern confirmed 2026-10-05)
  for (const region of REGION_NAMES) {
    for (const d of departments) {
      if (d.slug === "atfal") continue; // no evidence (no Thinkific course, not in fork rules): Atfal is local-only on atfalusa.org
      const aitmad = d.slug === "aitmad";
      push({ departmentSlug: d.slug, role: aitmad ? "regional_motamid" : "regional_nazim", level: "region", region, majlis: "",
        roleTitle: aitmad ? "Regional Motamid" : `Regional Nazim ${d.name}`, learnerEmail: `${d.mailboxPrefix}.${slugify(region)}@${MKA_DOMAIN}` });
    }
  }

  // local
  const defs = localRoleDefs(excluded);
  for (const [majlis, region] of Object.entries(MAJLIS_TO_REGION)) {
    const slug = slugify(majlis);
    for (const d of defs) {
      push({ departmentSlug: d.departmentSlug, role: d.role, level: "majlis", region, majlis, roleTitle: d.title, learnerEmail: `${d.prefix}.${slug}@${d.domain}` });
    }
    if (!excluded.includes("atfal")) for (const [prefix, role, title] of [["nazim", "nazim_atfal", "Nazim Atfal"], ["murabbi", "murabbi_atfal", "Murabbi Atfal"]] as const) {
      push({ departmentSlug: "atfal", role, level: "majlis", region, majlis, roleTitle: title, learnerEmail: `${prefix}.${slug}@${ATFAL_DOMAIN}` });
    }
  }
  return rows;
}

/** Which courses a roster row should be enrolled in (General always; department course when it has one). */
export function coursesFor(row: Pick<RosterRow, "departmentSlug">): { general: true; department: string | null } {
  return { general: true, department: row.departmentSlug || null };
}
