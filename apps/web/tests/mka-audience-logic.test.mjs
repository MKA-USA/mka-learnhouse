import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { resolveSectionMode, showsPreviewLabel, computeLearnerNotes, countSections, unknownValues, ruleWarnings, isRuleEditable } from "../components/mka/editor/logic.ts";
import { createAudienceStore } from "../components/mka/editor/store.ts";

const vectors = JSON.parse(
  readFileSync(new URL("../../api/src/tests/services/mka/vectors/audience_vectors.json", import.meta.url), "utf8"),
);
const V = vectors.viewers;
const showLocal = { v: 1, mode: "show", groups: [{ level: ["local"] }] };
const showRegional = { v: 1, mode: "show", groups: [{ level: ["regional"] }] };
const hideLocal = { v: 1, mode: "hide", groups: [{ level: ["local"] }] };
const AUTHOR = { kind: "author" };
const SELF = { kind: "self" };
const persona = (attributes) => ({ kind: "persona", label: "p", attributes });

const base = { view: AUTHOR, viewerState: "ready", viewer: V.local_tabligh_albany, canViewAll: false, editable: false, rule: showLocal };
const mode = (o) => resolveSectionMode({ ...base, ...o });

describe("resolveSectionMode: authoring (editable)", () => {
  test("author view is chrome even while /me is loading or failed", () => {
    expect(mode({ editable: true, viewerState: "loading", viewer: null })).toBe("chrome");
    expect(mode({ editable: true, viewerState: "error", viewer: null, rule: showRegional })).toBe("chrome");
  });
  test("persona preview: match => content, non-match => placeholder", () => {
    expect(mode({ editable: true, view: persona(V.local_tabligh_albany) })).toBe("content");
    expect(mode({ editable: true, view: persona(V.regional_qaid_northeast) })).toBe("placeholder");
    expect(mode({ editable: true, view: persona(null) })).toBe("placeholder");
  });
  test("as-me preview waits for /me, then evaluates", () => {
    expect(mode({ editable: true, view: SELF, viewerState: "loading", viewer: null })).toBe("loading");
    expect(mode({ editable: true, view: SELF })).toBe("content");
    expect(mode({ editable: true, view: SELF, rule: showRegional })).toBe("placeholder");
  });
});

describe("resolveSectionMode: viewing (not editable)", () => {
  test("no flash: nothing while /me is loading, whatever the flags", () => {
    expect(mode({ viewerState: "loading", viewer: null })).toBe("loading");
    expect(mode({ viewerState: "loading", viewer: null, canViewAll: true })).toBe("loading");
  });
  test("learner: match => content (no chrome), non-match => hidden", () => {
    expect(mode({})).toBe("content");
    expect(mode({ rule: showRegional })).toBe("hidden");
  });
  test("learner can never select a view: a tampered store is ignored", () => {
    expect(mode({ rule: showRegional, view: persona(V.regional_qaid_northeast) })).toBe("hidden");
    expect(mode({ rule: showRegional, view: SELF })).toBe("hidden");
  });
  test("canViewAll: author view shows everything with the badge (chrome)", () => {
    expect(mode({ canViewAll: true, rule: showRegional })).toBe("chrome");
  });
  test("canViewAll: preview match => content, non-match => placeholder", () => {
    expect(mode({ canViewAll: true, view: persona(V.local_tabligh_albany) })).toBe("content");
    expect(mode({ canViewAll: true, view: persona(V.local_tabligh_albany), rule: showRegional })).toBe("placeholder");
    expect(mode({ canViewAll: true, view: SELF, rule: showRegional })).toBe("placeholder");
    expect(mode({ canViewAll: true, view: SELF })).toBe("content");
  });
  test("/me failure or anonymous => null viewer: untargeted-for-others content shows, positive targeting hides", () => {
    expect(mode({ viewerState: "error", viewer: null, rule: showLocal })).toBe("hidden");
    expect(mode({ viewerState: "error", viewer: null, rule: hideLocal })).toBe("content");
    expect(mode({ viewerState: "ready", viewer: null, rule: showLocal })).toBe("hidden");
  });
  test("damaged or newer rules are hidden from learners (fail safe)", () => {
    expect(mode({ rule: { nonsense: true } })).toBe("hidden");
    expect(mode({ rule: { v: 2, mode: "show", groups: [{}] } })).toBe("hidden");
    expect(mode({ rule: null })).toBe("hidden");
  });
});

test("preview label only over matching content while previewing with authoring rights", () => {
  expect(showsPreviewLabel("content", SELF, true, false)).toBe(true);
  expect(showsPreviewLabel("content", SELF, false, true)).toBe(true);
  expect(showsPreviewLabel("content", AUTHOR, true, false)).toBe(false);
  expect(showsPreviewLabel("content", SELF, false, false)).toBe(false);
  expect(showsPreviewLabel("hidden", SELF, true, true)).toBe(false);
});

const section = (rule, text = "x") => ({ type: "mkaAudience", attrs: { id: text, rule }, content: [{ type: "paragraph", content: [{ type: "text", text }] }] });
const para = (text) => ({ type: "paragraph", content: text ? [{ type: "text", text }] : [] });
const doc = (...content) => ({ type: "doc", content });

describe("computeLearnerNotes", () => {
  test("recognized viewer with a hidden section: no unrecognized note", () => {
    const n = computeLearnerNotes(doc(para("hi"), section(showRegional)), V.local_tabligh_albany);
    expect(n).toEqual({ hiddenCount: 1, unrecognized: false, emptyLesson: false });
  });
  test("unrecognized viewer with a hidden section gets the note", () => {
    const n = computeLearnerNotes(doc(para("hi"), section(showLocal)), V.unrecognized_missing_row);
    expect(n.unrecognized).toBe(true);
    expect(n.emptyLesson).toBe(false);
  });
  test("unrecognized viewer but nothing hidden: no note", () => {
    const n = computeLearnerNotes(doc(para("hi"), section(hideLocal)), V.unrecognized_missing_row);
    expect(n).toEqual({ hiddenCount: 0, unrecognized: false, emptyLesson: false });
  });
  test("not_applicable and partial count as recognised", () => {
    expect(computeLearnerNotes(doc(section(showLocal)), V.not_officeholder).unrecognized).toBe(false);
    expect(computeLearnerNotes(doc(section(showRegional)), V.partial_tabligh_unknown_majlis).unrecognized).toBe(false);
  });
  test("anonymous viewer: no unrecognized note (no sign-in to recognise)", () => {
    expect(computeLearnerNotes(doc(section(showLocal)), null).unrecognized).toBe(false);
  });
  test("empty lesson: every top-level node is a hidden section or an empty paragraph", () => {
    const n = computeLearnerNotes(doc(para(""), section(showRegional, "a"), section(showRegional, "b")), V.local_tabligh_albany);
    expect(n.emptyLesson).toBe(true);
  });
  test("not empty when any real content remains", () => {
    expect(computeLearnerNotes(doc(para("keep"), section(showRegional)), V.local_tabligh_albany).emptyLesson).toBe(false);
    expect(computeLearnerNotes(doc(section(showLocal), section(showRegional, "b")), V.local_tabligh_albany).emptyLesson).toBe(false);
  });
  test("an empty document is not an 'empty lesson' (nothing was hidden)", () => {
    expect(computeLearnerNotes(doc(para("")), V.local_tabligh_albany).emptyLesson).toBe(false);
    expect(computeLearnerNotes(null, null)).toEqual({ hiddenCount: 0, unrecognized: false, emptyLesson: false });
  });
});

test("countSections counts nested too", () => {
  expect(countSections(doc(section(showLocal), para("x"), { type: "mkaAudience", content: [section(showLocal, "in")] }))).toBe(3);
});

describe("warnings", () => {
  const options = {
    levels: [{ key: "local", label: "Local" }],
    departments: [{ key: "tabligh", name: "Tabligh", aka: [] }],
    roles: [{ key: "qaid", title: "Qaid", plural: "Qaids" }],
    regions: [{ name: "Northeast" }],
    majlis: [{ name: "Albany", region: "Northeast" }],
  };
  test("unknown values are reported once", () => {
    const rule = { v: 1, mode: "show", groups: [{ department: ["tabligh", "rishta_nata_old"] }, { majlis: ["Gotham", "Albany"] }] };
    expect(unknownValues(rule, options)).toEqual(["rishta_nata_old", "Gotham"]);
    expect(unknownValues(rule, undefined)).toEqual([]);
  });
  test("ruleWarnings", () => {
    expect(ruleWarnings({ bad: 1 }, options, false)).toEqual([{ kind: "invalid" }]);
    expect(ruleWarnings({ v: 2, mode: "show", groups: [{}] }, options, false)).toEqual([{ kind: "newer_version" }]);
    expect(ruleWarnings(showLocal, options, true)).toEqual([{ kind: "zero" }]);
    expect(ruleWarnings(showLocal, options, false)).toEqual([]);
  });
  test("newer rules are read-only for authors; damaged ones stay editable so they can be repaired", () => {
    expect(isRuleEditable({ v: 2, mode: "show", groups: [{}] })).toBe(false);
    expect(isRuleEditable({ nonsense: 1 })).toBe(true);
    expect(isRuleEditable(showLocal)).toBe(true);
  });
});

describe("audience store", () => {
  test("defaults, set, subscribe", () => {
    const s = createAudienceStore();
    expect(s.get().view).toEqual({ kind: "author" });
    let calls = 0;
    const off = s.subscribe(() => calls++);
    s.set({ view: { kind: "self" } });
    s.set({ view: s.get().view }); // same value: no notification
    expect(calls).toBe(1);
    off();
    s.set({ openPickerFor: "a" });
    expect(calls).toBe(1);
    expect(s.get().openPickerFor).toBe("a");
  });
});
