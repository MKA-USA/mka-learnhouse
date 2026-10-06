import { describe, expect, test } from "bun:test";
import {
  applyPreset, hasRoleKey, normalizeRule, replaceValue, resolvePresets, sameGroups,
  selectWholeRegion, setMode, toggleValue, unknownValues,
} from "../components/mka/audience/rule-edit.ts";

const o = {
  levels: [{ key: "local", label: "Local" }, { key: "regional", label: "Regional" }, { key: "national", label: "National" }],
  departments: [{ key: "tabligh", name: "Tabligh", aka: [] }, { key: "talim", name: "Talim", aka: [] }],
  roles: [{ key: "qaid", title: "Qaid", plural: "Qaids" }],
  regions: [{ name: "Northeast" }],
  majlis: [{ name: "Albany", region: "Northeast" }, { name: "Boston", region: "Northeast" }],
};
const base = { v: 1, mode: "show", groups: [{}] };

describe("rule edit", () => {
  test("normalize drops empty lists and dedupes", () => {
    const r = normalizeRule({ ...base, groups: [{ level: [], department: ["tabligh", "tabligh"] }] });
    expect(r.groups[0]).toEqual({ department: ["tabligh"] });
  });
  test("normalize refreshes label only when options given", () => {
    expect(normalizeRule({ ...base, label: "stale" }).label).toBeUndefined();
    expect(normalizeRule(base, o).label).toBe("All officeholders");
  });
  test("toggle adds then removes and cleans the key", () => {
    const a = toggleValue(base, "level", "local");
    expect(a.groups[0].level).toEqual(["local"]);
    const b = toggleValue(a, "level", "local");
    expect(b.groups[0]).toEqual({});
  });
  test("replace swaps in place", () => {
    const r = replaceValue({ ...base, groups: [{ department: ["old", "talim"] }] }, "department", "old", "tabligh");
    expect(r.groups[0].department).toEqual(["tabligh", "talim"]);
  });
  test("mode switch keeps groups", () => {
    expect(setMode({ ...base, groups: [{ level: ["local"] }] }, "hide").mode).toBe("hide");
  });
  test("whole region converts majlis to region row", () => {
    const start = { ...base, groups: [{ majlis: ["Albany", "Houston"] }] };
    const r = selectWholeRegion(start, "Northeast", ["Albany", "Boston"]);
    expect(r.groups[0]).toEqual({ majlis: ["Houston"], region: ["Northeast"] });
  });
  test("whole region removes emptied majlis key", () => {
    const r = selectWholeRegion({ ...base, groups: [{ majlis: ["Albany"] }] }, "Northeast", ["Albany", "Boston"]);
    expect(r.groups[0]).toEqual({ region: ["Northeast"] });
  });
  test("extra groups survive editing group 0", () => {
    const r = toggleValue({ ...base, groups: [{}, { role: ["qaid"] }] }, "level", "local");
    expect(r.groups).toEqual([{ level: ["local"] }, { role: ["qaid"] }]);
  });
  test("unknown values", () => {
    const r = { ...base, groups: [{ department: ["tabligh", "rishta_old"], majlis: ["Narnia"] }] };
    expect(unknownValues(r, o)).toEqual([
      { key: "department", value: "rishta_old" },
      { key: "majlis", value: "Narnia" },
    ]);
  });
  test("presets: My department filled or hidden", () => {
    const presets = [
      { id: "local", label: "Local", rule: { v: 1, mode: "show", groups: [{ level: ["local"] }] } },
      { id: "mine", label: "My department", rule: { v: 1, mode: "show", groups: [{}] }, needs_author_department: true },
    ];
    const withDept = resolvePresets(presets, "tabligh", ["tabligh"]);
    expect(withDept.map((p) => p.id)).toEqual(["local", "mine"]);
    expect(withDept[1].rule.groups[0]).toEqual({ department: ["tabligh"] });
    expect(resolvePresets(presets, null, ["tabligh"]).map((p) => p.id)).toEqual(["local"]);
    expect(resolvePresets(presets, "bogus", ["tabligh"]).map((p) => p.id)).toEqual(["local"]);
  });
  test("applyPreset resets to show mode", () => {
    const r = applyPreset({ id: "x", label: "x", rule: { v: 1, mode: "hide", groups: [{ level: ["local"] }] } });
    expect(r.mode).toBe("show");
  });
  test("sameGroups and hasRoleKey", () => {
    expect(sameGroups({ ...base, groups: [{ level: ["local"] }] }, { ...base, mode: "hide", groups: [{ level: ["local"], role: [] }] })).toBe(true);
    expect(hasRoleKey({ ...base, groups: [{ role: ["qaid"] }] })).toBe(true);
    expect(hasRoleKey(base)).toBe(false);
  });
});
