import type { RosterRow } from "../roster/generate";
import { MKA_DOMAIN, ATFAL_DOMAIN } from "../roster/generate";
import { parseCsv } from "./csv";
import { departmentFromEmail, regionOfMajlis, resolveDepartment, resolveMajlis, resolveRegion } from "./resolve";
import { type Issue, SHEET_ERROR_RE } from "./types";
import { slugify } from "../roster/generate";

export interface OverrideInput {
  departmentSlug: string; level: "national" | "region" | "majlis"; role: string; region: string; majlis: string;
  learnerEmail: string | null; personName: string | null; note: string | null;
}
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const FILE = "directory_overrides.csv";

export function parseOverrides(csv: string, file = FILE): { rows: OverrideInput[]; issues: Issue[] } {
  const { headers, rows } = parseCsv(csv);
  const issues: Issue[] = [];
  const idx = (n: string) => headers.indexOf(n);
  if (idx("department") < 0) { issues.push({ file, line: 1, severity: "error", code: "missing-column", message: "missing column: department" }); return { rows: [], issues }; }
  const out = new Map<string, OverrideInput>();
  const emailSeen = new Map<string, number>();
  for (const r of rows) {
    if (r.cells.length !== headers.length && (r.cells.length < headers.length || r.cells.slice(headers.length).some((c) => c.trim()))) {
      issues.push({ file, line: r.line, severity: "error", code: "shifted-row", message: `expected ${headers.length} columns, found ${r.cells.length}; row skipped` }); continue;
    }
    const get = (n: string) => { const c = (r.cells[idx(n)] ?? "").trim(); if (SHEET_ERROR_RE.test(c)) { issues.push({ file, line: r.line, severity: "warn", code: "sheet-error", message: `${n} contains ${c}; treated as blank` }); return ""; } return c; };
    let dept = resolveDepartment(get("department")) ?? (get("department") === "" ? "" : null);
    if (dept === null) { issues.push({ file, line: r.line, severity: "error", code: "unknown-department", message: `unknown department "${get("department")}"; row skipped` }); continue; }
    let majlis = ""; const rawM = get("majlis");
    if (rawM) {
      const m = resolveMajlis(rawM);
      if (!m.name) { issues.push({ file, line: r.line, severity: "error", code: "unknown-majlis", message: `unknown Majlis "${rawM}"; row skipped` }); continue; }
      if (m.aliased) issues.push({ file, line: r.line, severity: "info", code: "slug-alias", message: `Majlis "${rawM}" resolved to ${m.name}` });
      majlis = m.name;
    }
    let region = ""; const rawR = get("region");
    if (rawR) { const rg = resolveRegion(rawR); if (!rg && !majlis) { issues.push({ file, line: r.line, severity: "error", code: "unknown-region", message: `unknown region "${rawR}"; row skipped` }); continue; } region = rg ?? ""; }
    if (majlis) { const want = regionOfMajlis(majlis); if (region && region !== want) issues.push({ file, line: r.line, severity: "warn", code: "region-mismatch", message: `${majlis} is in ${want}, row says ${region}; using ${want}` }); region = want; }
    const level: OverrideInput["level"] = majlis ? "majlis" : region ? "region" : "national";
    const emailRaw = get("learner_email").toLowerCase();
    let email: string | null = emailRaw || null;
    if (email && !EMAIL_RE.test(email)) { issues.push({ file, line: r.line, severity: "error", code: "bad-email", message: `"${email}" is not an email; row skipped` }); continue; }
    if (email) {
      const domain = email.split("@")[1]!;
      if (domain !== MKA_DOMAIN && domain !== ATFAL_DOMAIN) issues.push({ file, line: r.line, severity: "warn", code: "foreign-domain", message: `${email} is not on ${MKA_DOMAIN}/${ATFAL_DOMAIN}` });
      const imp = departmentFromEmail(email);
      if (imp.department && dept && imp.department !== dept) {
        const pair = new Set([imp.department, dept]);
        if (pair.has("atfal") && pair.has("amoor-e-tuluba")) {
          issues.push({ file, line: r.line, severity: "warn", code: "swapped-columns", message: `Atfal/Amoor-e-Tuluba swap: row department ${dept} but mailbox belongs to ${imp.department}; using ${imp.department}` });
          dept = imp.department;
        } else { issues.push({ file, line: r.line, severity: "error", code: "department-mismatch", message: `row department ${dept} but mailbox prefix belongs to ${imp.department}; row skipped` }); continue; }
      }
      if (imp.majlisSlug && majlis && imp.majlisSlug !== slugify(majlis) && resolveMajlis(imp.majlisSlug).name !== majlis) {
        issues.push({ file, line: r.line, severity: "warn", code: "email-majlis-mismatch", message: `mailbox says "${imp.majlisSlug}" but row Majlis is ${majlis}` });
      }
      const first = emailSeen.get(email);
      if (first !== undefined) issues.push({ file, line: r.line, severity: "warn", code: "duplicate-mailbox", message: `${email} also used on line ${first}` });
      else emailSeen.set(email, r.line);
    }
    const key = [dept, level, get("role"), region, majlis].join("|");
    if (out.has(key)) issues.push({ file, line: r.line, severity: "warn", code: "duplicate-key", message: `duplicate override for ${key}; later row wins` });
    out.set(key, { departmentSlug: dept, level, role: get("role"), region, majlis, learnerEmail: email, personName: get("person_name") || null, note: get("note") || null });
  }
  return { rows: [...out.values()], issues };
}

/** Apply overrides over generated roster rows. Overridden rows get source 'override'. */
export function applyOverrides<T extends RosterRow>(roster: T[], overrides: OverrideInput[], file = FILE): { roster: T[]; issues: Issue[] } {
  const issues: Issue[] = [];
  const out = roster.map((r) => ({ ...r }));
  for (const o of overrides) {
    const matches = out.filter((r) => r.departmentSlug === o.departmentSlug && r.level === o.level && r.region === o.region && r.majlis === o.majlis && (!o.role || r.role === o.role));
    if (matches.length === 0) { issues.push({ file, line: 0, severity: "warn", code: "override-no-match", message: `no roster role for ${o.departmentSlug || "(no dept)"}/${o.level}/${o.region || "-"}/${o.majlis || "-"}${o.role ? `/${o.role}` : ""}` }); continue; }
    if (matches.length > 1) { issues.push({ file, line: 0, severity: "warn", code: "override-ambiguous", message: `${matches.length} roles match ${o.departmentSlug}/${o.majlis || o.region}; add a role column (e.g. nazim_atfal)` }); continue; }
    const m = matches[0]!;
    if (o.learnerEmail) m.learnerEmail = o.learnerEmail;
    if (o.personName) m.personName = o.personName;
    m.source = "override";
  }
  return { roster: out, issues };
}

export function parseNames(csv: string, file = "names.csv"): { names: Map<string, string>; issues: Issue[] } {
  const { headers, rows } = parseCsv(csv);
  const issues: Issue[] = []; const names = new Map<string, string>();
  const ie = headers.indexOf("email") >= 0 ? headers.indexOf("email") : headers.indexOf("learner_email"), inm = headers.indexOf("name") >= 0 ? headers.indexOf("name") : headers.indexOf("person_name");
  if (ie < 0 || inm < 0) { issues.push({ file, line: 1, severity: "error", code: "missing-column", message: "need columns email,name" }); return { names, issues }; }
  for (const r of rows) {
    if (r.cells.length !== headers.length && (r.cells.length < headers.length || r.cells.slice(headers.length).some((c) => c.trim()))) { issues.push({ file, line: r.line, severity: "error", code: "shifted-row", message: `expected ${headers.length} columns, found ${r.cells.length}; row skipped` }); continue; }
    const email = (r.cells[ie] ?? "").trim().toLowerCase(); const name = (r.cells[inm] ?? "").trim();
    if (SHEET_ERROR_RE.test(email) || SHEET_ERROR_RE.test(name)) { issues.push({ file, line: r.line, severity: "warn", code: "sheet-error", message: "cell contains a spreadsheet error; row skipped" }); continue; }
    if (!EMAIL_RE.test(email)) { issues.push({ file, line: r.line, severity: "error", code: "bad-email", message: `"${email}" is not an email; row skipped` }); continue; }
    if (!name || /^(n\/a|none|tbd|missing|-)$/i.test(name)) { issues.push({ file, line: r.line, severity: "warn", code: "missing-name", message: `${email} has no usable name` }); continue; }
    if (EMAIL_RE.test(name)) { issues.push({ file, line: r.line, severity: "error", code: "shifted-row", message: `${email}: name column holds an email (shifted columns); row skipped` }); continue; }
    const prev = names.get(email);
    if (prev && prev !== name) issues.push({ file, line: r.line, severity: "warn", code: "duplicate-mailbox", message: `${email} listed with different names; later row wins` });
    names.set(email, name);
  }
  return { names, issues };
}
