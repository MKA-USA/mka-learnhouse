import majlisData from "../data/majlis-regions.json";
import { DEPARTMENTS } from "../seed/departments";

export const ROSTER_SOURCE = "formula";
export const MKA_DOMAIN = "mkausa.org";
export const ATFAL_DOMAIN = "atfalusa.org";

export interface RosterRow {
  departmentSlug: string; role: string; level: "national" | "region" | "majlis";
  region: string; majlis: string; roleTitle: string; learnerEmail: string;
  personName?: string | null; source: string; flags?: string[];
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
}

export function localRoleDefs() {
  const dept = DEPARTMENTS.map((d) => ({
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
  const nameOf = (email: string) => opts.names?.get(email.toLowerCase()) ?? null;
  const push = (r: Omit<RosterRow, "personName" | "source">) =>
    rows.push({ ...r, learnerEmail: r.learnerEmail.toLowerCase(), personName: nameOf(r.learnerEmail), source: ROSTER_SOURCE });

  // national
  for (const d of DEPARTMENTS) {
    const isAitmad = d.slug === "aitmad";
    push({ departmentSlug: d.slug, role: isAitmad ? "motamid" : "mohtamim", level: "national", region: "", majlis: "",
      roleTitle: isAitmad ? "National Motamid" : `Mohtamim ${d.name}`, learnerEmail: `${d.mailboxPrefix}@${MKA_DOMAIN}` });
  }
  push({ departmentSlug: "", role: "sadr", level: "national", region: "", majlis: "", roleTitle: "Sadr", learnerEmail: `sadr@${MKA_DOMAIN}` });
  for (const s of NATIONAL_STAFF) push({ departmentSlug: "", role: "national_staff", level: "national", region: "", majlis: "", roleTitle: `National staff (${s})`, learnerEmail: `${s}@${MKA_DOMAIN}` });

  // regional qaids
  for (const region of REGION_NAMES) {
    push({ departmentSlug: "", role: "regional_qaid", level: "region", region, majlis: "", roleTitle: "Regional Qaid", learnerEmail: `qaid.${slugify(region)}@${MKA_DOMAIN}` });
  }

  // local
  const defs = localRoleDefs();
  for (const [majlis, region] of Object.entries(MAJLIS_TO_REGION)) {
    const slug = slugify(majlis);
    for (const d of defs) {
      push({ departmentSlug: d.departmentSlug, role: d.role, level: "majlis", region, majlis, roleTitle: d.title, learnerEmail: `${d.prefix}.${slug}@${d.domain}` });
    }
    for (const [prefix, role, title] of [["nazim", "nazim_atfal", "Nazim Atfal"], ["murabbi", "murabbi_atfal", "Murabbi Atfal"]] as const) {
      push({ departmentSlug: "atfal", role, level: "majlis", region, majlis, roleTitle: title, learnerEmail: `${prefix}.${slug}@${ATFAL_DOMAIN}` });
    }
  }
  return rows;
}

/** Which courses a roster row should be enrolled in (General always; department course when it has one). */
export function coursesFor(row: Pick<RosterRow, "departmentSlug">): { general: true; department: string | null } {
  return { general: true, department: row.departmentSlug || null };
}
