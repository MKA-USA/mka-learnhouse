import { describe, expect, test } from "bun:test";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { activeDepartments, resolveConfig, withoutExcluded } from "../src/config";
import { coursesFor, generateRoster, MAJLIS_TO_REGION, REGION_NAMES, slugify } from "../src/roster";

const rows = generateRoster();
describe("roster generator", () => {
  test("52 Majlis (51 + Muqami) x 22 local roles, 10 regional qaids, national mailboxes", () => {
    expect(Object.keys(MAJLIS_TO_REGION).length).toBe(52);
    expect(REGION_NAMES.length).toBe(10);
    expect(rows.filter((r) => r.level === "majlis").length).toBe(52 * 22);
    expect(rows.filter((r) => r.role === "regional_qaid").length).toBe(10);
    expect(rows.filter((r) => r.level === "region").length).toBe(10 + 10 * 20);
    expect(rows.filter((r) => r.level === "national").length).toBe(20 + 1 + 1 + 5); // 20 department heads (Atfal excluded) + Sadr + Mohtamim Muqami + 5 staff
  });
  test("every Majlis has every role", () => {
    for (const m of Object.keys(MAJLIS_TO_REGION)) {
      const roles = rows.filter((r) => r.majlis === m);
      expect(new Set(roles.map((r) => `${r.role}:${r.departmentSlug}`)).size).toBe(22);
    }
  });
  test("email formulas", () => {
    const e = (f: (r: (typeof rows)[number]) => boolean) => rows.find(f)?.learnerEmail;
    expect(e((r) => r.role === "motamid" && r.majlis === "Albany")).toBe("motamid.albany@mkausa.org");
    expect(e((r) => r.departmentSlug === "nau-mubaeen" && r.majlis === "Saint Louis")).toBe("nau-mubaeen.saintlouis@mkausa.org");
    expect(e((r) => r.departmentSlug === "new-immigrants" && r.majlis === "RTP")).toBe("immigrants.rtp@mkausa.org");
    expect(e((r) => r.role === "nazim_atfal" && r.majlis === "Boston")).toBeUndefined(); // Atfal excluded by default
    expect(generateRoster({ excludedDepartments: [] }).find((r) => r.role === "nazim_atfal" && r.majlis === "Boston")?.learnerEmail).toBe("nazim.boston@atfalusa.org");
    expect(e((r) => r.role === "regional_qaid" && r.region === "New York Metro")).toBe("qaid.newyorkmetro@mkausa.org");
    expect(e((r) => r.role === "mohtamim" && r.departmentSlug === "rishta-nata")).toBe("rishtanata@mkausa.org");
    expect(e((r) => r.role === "motamid" && r.level === "national")).toBe("motamid@mkausa.org");
  });
  test("regional department officers: 10 regions x 20 departments (not Atfal), pattern confirmed", () => {
    const reg = rows.filter((r) => r.role === "regional_nazim" || r.role === "regional_motamid");
    expect(reg.length).toBe(200);
    expect(reg.every((r) => r.source === "formula")).toBe(true);
    const e = (d: string, rg: string) => reg.find((r) => r.departmentSlug === d && r.region === rg)?.learnerEmail;
    expect(e("mohasib", "East")).toBe("mohasib.east@mkausa.org");
    expect(e("aitmad", "Great Lakes")).toBe("motamid.greatlakes@mkausa.org");
    expect(e("new-immigrants", "New York Metro")).toBe("immigrants.newyorkmetro@mkausa.org");
    expect(rows.filter((r) => r.level === "majlis" || r.role === "regional_qaid").every((r) => r.source === "formula")).toBe(true);
  });
  test("Muqami: one national mailbox, no regional-department set, no department course", () => {
    expect(REGION_NAMES).not.toContain("Muqami");
    const nat = rows.filter((r) => r.learnerEmail === "muqami@mkausa.org");
    expect(nat.length).toBe(1);
    expect(nat[0]).toMatchObject({ level: "national", role: "mohtamim", roleTitle: "Mohtamim Muqami", departmentSlug: "" });
    expect(coursesFor(nat[0]!)).toEqual({ general: true, department: null });
    // region "Muqami" has no regional rows at all; its only rows are the 22 chapter (Majlis) roles (24 minus the 2 Atfal roles, excluded by default)
    expect(rows.filter((r) => r.region === "Muqami" && r.level !== "majlis").length).toBe(0);
    expect(rows.filter((r) => r.majlis === "Muqami").length).toBe(22);
    expect(rows.filter((r) => r.learnerEmail.includes(".muqami@")).length).toBe(22);
  });
  test("Atfal is excluded everywhere by default and comes back with one switch", () => {
    expect(rows.filter((r) => r.departmentSlug === "atfal" || r.learnerEmail.endsWith("@atfalusa.org")).length).toBe(0);
    const on = generateRoster({ excludedDepartments: [] });
    expect(on.filter((r) => r.departmentSlug === "atfal").map((r) => r.level + ":" + r.role).sort().filter((x, i, a) => a.indexOf(x) === i)).toEqual(["majlis:murabbi_atfal", "majlis:nazim_atfal", "national:mohtamim"]);
    expect(on.length - rows.length).toBe(1 + 52 * 2);
  });
  test("config helpers", () => {
    expect(resolveConfig().excludedDepartments).toEqual(["atfal"]);
    expect(resolveConfig({ includeAtfal: true }).excludedDepartments).toEqual([]);
    expect(activeDepartments(["atfal"]).length).toBe(20);
    expect(withoutExcluded([{ departmentSlug: "atfal" }, { departmentSlug: "" }, { departmentSlug: "maal" }], ["atfal"]).length).toBe(2);
  });
  test("emails are unique", () => {
    expect(new Set(rows.map((r) => r.learnerEmail)).size).toBe(rows.length);
  });
  test("names enrich by email", () => {
    const r = generateRoster({ names: new Map([["tabligh.boston@mkausa.org", "Test Person"]]) });
    expect(r.find((x) => x.learnerEmail === "tabligh.boston@mkausa.org")?.personName).toBe("Test Person");
  });
  test("slugify", () => { expect(slugify("Saint Louis")).toBe("saintlouis"); expect(slugify("Syracuse-Binghamton")).toBe("syracuse-binghamton"); });
});

const regionRules = fileURLToPath(new URL("../../../../../apps/api/src/services/mka/identity_rules/2026.2.json", import.meta.url));
describe.skipIf(!existsSync(regionRules))("region slugs conform to rules", () => {
  test("region slugs match", () => {
    const rules = JSON.parse(readFileSync(regionRules, "utf8"));
    expect(REGION_NAMES.map(slugify).sort()).toEqual(Object.keys(rules.regions).sort());
  });
});

const pyPath = fileURLToPath(new URL("../../../../../apps/api/src/services/users/mka_profile.py", import.meta.url));
describe.skipIf(!existsSync(pyPath))("majlis map conforms to fork source", () => {
  test("every key of the JSON map appears in mka_profile.py", () => {
    const py = readFileSync(pyPath, "utf8");
    for (const [m, r] of Object.entries(MAJLIS_TO_REGION)) expect(py).toContain(`"${m}": "${r}"`);
  });
});
