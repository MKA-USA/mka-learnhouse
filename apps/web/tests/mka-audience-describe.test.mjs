import { describe, expect, test } from "bun:test";
import {
  ariaLabelForRule, describeRule, joinList, levelTone,
} from "../components/mka/audience/describe.ts";

const o = {
  levels: [
    { key: "national", label: "National" },
    { key: "regional", label: "Regional" },
    { key: "local", label: "Local" },
  ],
  departments: [
    { key: "tabligh", name: "Tabligh", aka: [] },
    { key: "tarbiyyat", name: "Tarbiyyat", aka: [] },
    { key: "talim", name: "Talim", aka: [] },
    { key: "mal", name: "Maal", aka: [] },
    { key: "rishta_nata", name: "Rishta Nata", aka: [] },
  ],
  roles: [
    { key: "qaid", title: "Qaid", plural: "Qaids" },
    { key: "naib_qaid", title: "Naib Qaid", plural: "Naib Qaids" },
    { key: "regional_qaid", title: "Regional Qaid", plural: "Regional Qaids" },
    { key: "motamid", title: "Motamid", plural: "Motamids" },
  ],
  regions: [{ name: "Northeast" }, { name: "Mid-Atlantic" }, { name: "West" }],
  majlis: [
    { name: "Albany", region: "Northeast" },
    { name: "Boston", region: "Northeast" },
    { name: "Houston", region: "South" },
    { name: "Syracuse", region: "Northeast" },
    { name: "Buffalo", region: "Northeast" },
  ],
};
const show = (...groups) => ({ v: 1, mode: "show", groups });
const hide = (...groups) => ({ v: 1, mode: "hide", groups });

const cases = [
  ["local + dept", show({ level: ["local"], department: ["tabligh"] }), "Local officeholders in Tabligh"],
  ["local or regional", show({ level: ["local", "regional"] }), "Local or Regional officeholders"],
  ["regional qaid role", show({ role: ["regional_qaid"] }), "Regional Qaids"],
  ["empty group", show({}), "All officeholders"],
  ["anyone signed in", show({ officeholder: false }), "Everyone signed in"],
  ["officeholder true explicit", show({ officeholder: true }), "All officeholders"],
  ["single level", show({ level: ["national"] }), "National officeholders"],
  ["three levels", show({ level: ["national", "regional", "local"] }), "National, Regional or Local officeholders"],
  ["two roles", show({ role: ["qaid", "naib_qaid"] }), "Qaids or Naib Qaids"],
  ["three roles", show({ role: ["qaid", "naib_qaid", "motamid"] }), "Qaids, Naib Qaids or Motamids"],
  ["four roles", show({ role: ["qaid", "naib_qaid", "motamid", "regional_qaid"] }), "Qaids, Naib Qaids and 2 more"],
  ["role + level", show({ role: ["qaid"], level: ["local"] }), "Qaids at the Local level"],
  ["role + two levels", show({ role: ["qaid"], level: ["local", "regional"] }), "Qaids at the Local or Regional level"],
  ["one department", show({ department: ["tabligh"] }), "Officeholders in Tabligh"],
  ["two departments", show({ department: ["tabligh", "talim"] }), "Officeholders in Tabligh or Talim"],
  ["three departments", show({ department: ["tabligh", "talim", "mal"] }), "Officeholders in Tabligh, Talim or Maal"],
  ["five departments", show({ department: ["tabligh", "talim", "mal", "tarbiyyat", "rishta_nata"] }), "Officeholders in Tabligh, Talim and 3 more"],
  ["region", show({ region: ["Northeast"] }), "Officeholders in the Northeast region"],
  ["two regions", show({ region: ["Northeast", "West"] }), "Officeholders in the Northeast or West regions"],
  ["level + region", show({ level: ["regional"], region: ["Northeast"] }), "Regional officeholders in the Northeast region"],
  ["role + region", show({ role: ["qaid"], region: ["Northeast"] }), "Qaids in the Northeast region"],
  ["majlis", show({ majlis: ["Albany"] }), "Officeholders in Albany"],
  ["two majlis", show({ majlis: ["Albany", "Boston"] }), "Officeholders in Albany or Boston"],
  ["five majlis", show({ majlis: ["Albany", "Boston", "Houston", "Syracuse", "Buffalo"] }), "Officeholders in Albany, Boston and 3 more"],
  ["dept + majlis", show({ level: ["local"], department: ["tabligh"], majlis: ["Albany"] }), "Local officeholders in Tabligh, in Albany"],
  ["signed-in + dept", show({ officeholder: false, department: ["tabligh"] }), "Signed-in people in Tabligh"],
  ["two groups", show({ level: ["local"], department: ["tabligh"] }, { role: ["regional_qaid"] }), "Local officeholders in Tabligh, plus Regional Qaids"],
  ["hide level", hide({ level: ["national"] }), "Everyone except national officeholders"],
  ["hide local dept", hide({ level: ["local"], department: ["tabligh"] }), "Everyone except local officeholders in Tabligh"],
  ["hide role", hide({ role: ["regional_qaid"] }), "Everyone except Regional Qaids"],
  ["hide all officeholders", hide({}), "Everyone except all officeholders"],
  ["hide everyone", hide({ officeholder: false }), "Nobody signed in"],
  ["hide dept", hide({ department: ["tabligh"] }), "Everyone except Officeholders in Tabligh".replace("Officeholders", "officeholders")],
  ["unknown department", show({ department: ["rishta_old"] }), "Officeholders in rishta_old (unknown)"],
  ["unknown role", show({ role: ["gadfly"] }), "gadfly (unknown)"],
  ["unknown level", show({ level: ["galactic"] }), "galactic (unknown) officeholders"],
  ["unknown region", show({ region: ["Atlantis"] }), "Officeholders in the Atlantis (unknown) region"],
  ["unknown majlis", show({ majlis: ["Narnia"] }), "Officeholders in Narnia (unknown)"],
  ["unknown group key", show({ nope: ["x"] }), "All officeholders (unknown filter)"],
  ["invalid: not object", null, "Audience needs fixing"],
  ["invalid: bad mode", { v: 1, mode: "maybe", groups: [{}] }, "Audience needs fixing"],
  ["invalid: empty groups", { v: 1, mode: "show", groups: [] }, "Audience needs fixing"],
  ["invalid: list not array", { v: 1, mode: "show", groups: [{ level: "local" }] }, "Audience needs fixing"],
  ["invalid: officeholder not bool", { v: 1, mode: "show", groups: [{ officeholder: "yes" }] }, "Audience needs fixing"],
  ["newer version", { v: 2, mode: "show", groups: [{}] }, "Made with a newer editor"],
  ["empty arrays ignored", show({ level: [], department: [] }), "All officeholders"],
];

describe("describeRule", () => {
  for (const [name, rule, expected] of cases) {
    test(name, () => expect(describeRule(rule, o)).toBe(expected));
  }
});

describe("joinList", () => {
  test("shapes", () => {
    expect(joinList([])).toBe("");
    expect(joinList(["A"])).toBe("A");
    expect(joinList(["A", "B"])).toBe("A or B");
    expect(joinList(["A", "B", "C"])).toBe("A, B or C");
    expect(joinList(["A", "B", "C", "D"])).toBe("A, B and 2 more");
  });
});

describe("ariaLabelForRule", () => {
  test("show", () => {
    expect(ariaLabelForRule(show({ level: ["local"], department: ["tabligh"] }), o)).toBe("Section visible to Local officeholders in Tabligh");
  });
  test("hide", () => {
    expect(ariaLabelForRule(hide({ level: ["national"] }), o)).toBe("Section visible to Everyone except national officeholders");
  });
  test("invalid", () => {
    expect(ariaLabelForRule({}, o)).toBe("Section audience needs fixing");
  });
});

describe("levelTone", () => {
  test("single levels", () => {
    expect(levelTone(show({ level: ["national"] }))).toBe("national");
    expect(levelTone(show({ level: ["regional"], role: ["regional_qaid"] }))).toBe("regional");
    expect(levelTone(show({ level: ["local"] }))).toBe("local");
  });
  test("mixed", () => {
    expect(levelTone(show({ level: ["local", "regional"] }))).toBe("mixed");
    expect(levelTone(show({}))).toBe("mixed");
    expect(levelTone(show({ level: ["local"] }, { level: ["national"] }))).toBe("mixed");
    expect(levelTone(show({ officeholder: false, level: ["local"] }))).toBe("mixed");
    expect(levelTone(null)).toBe("mixed");
  });
  test("hide wins", () => {
    expect(levelTone(hide({ level: ["local"] }))).toBe("hide");
  });
});
