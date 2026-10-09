import { afterEach, describe, expect, test } from "bun:test";
import {
  DEFAULT_DRAFT, buildPayload, confirmText, draftFromState, draftsEqual, needsEnrollConfirm,
  normalizeOptions, previewText, resultText, sampleText, toggleValue, validateDraft,
} from "../components/mka/course-audience/logic.ts";
import { mkaCourseAudienceEnabled } from "../services/mka/courseAudienceFlag.ts";

const rule = (o = {}) => ({ departments: [], levels: [], roles: [], ...o });
const draft = (o = {}) => ({ ...DEFAULT_DRAFT, ...o });

describe("buildPayload", () => {
  test("non-custom audiences send an empty rule, even if rule has stale values", () => {
    expect(buildPayload(draft({ audience: "everyone", mode: "required", rule: rule({ roles: ["x"] }) })))
      .toEqual({ audience: "everyone", mode: "required", rule: {} });
  });
  test("custom omits empty lists, dedupes, drops blanks", () => {
    expect(buildPayload(draft({ audience: "custom", rule: rule({ departments: ["maal", "maal", ""], levels: ["local"] }) })))
      .toEqual({ audience: "custom", mode: "optin", rule: { departments: ["maal"], levels: ["local"] } });
  });
});

describe("validateDraft", () => {
  test("custom with no filter is invalid", () => {
    expect(validateDraft(draft({ audience: "custom" }))).toMatch(/at least one/);
  });
  test("custom with a value, and non-custom, are valid", () => {
    expect(validateDraft(draft({ audience: "custom", rule: rule({ roles: ["secretary"] }) }))).toBeNull();
    expect(validateDraft(draft({ audience: "everyone" }))).toBeNull();
  });
});

describe("draft helpers", () => {
  test("draftFromState handles none/null rule", () => {
    expect(draftFromState({ audience: null })).toBeNull();
    expect(draftFromState({ audience: "officeholders", mode: "required", rule: null, usergroup_id: 1, matched_count: 3 }))
      .toEqual({ audience: "officeholders", mode: "required", rule: rule() });
  });
  test("toggleValue adds and removes", () => {
    expect(toggleValue(["a"], "b")).toEqual(["a", "b"]);
    expect(toggleValue(["a", "b"], "a")).toEqual(["b"]);
  });
  test("draftsEqual ignores irrelevant rule values for non-custom", () => {
    expect(draftsEqual(draft({ audience: "everyone", rule: rule({ roles: ["x"] }) }), draft({ audience: "everyone" }))).toBe(true);
    expect(draftsEqual(draft({ mode: "required" }), draft())).toBe(false);
    expect(draftsEqual(null, null)).toBe(true);
    expect(draftsEqual(null, draft())).toBe(false);
  });
});

describe("preview text", () => {
  const p = { matched_count: 12, would_enroll: 5, sample: [{ user_id: 1, name: "A", email: "a@x" }, { user_id: 2, name: "", email: "b@x" }] };
  test("required shows enroll count; optin says nobody enrolled", () => {
    expect(previewText(p, "required")).toBe("12 people match · 5 will be enrolled now");
    expect(previewText(p, "optin")).toContain("nobody is enrolled automatically");
    expect(previewText({ ...p, matched_count: 1 }, "optin")).toStartWith("1 person matches");
  });
  test("sampleText falls back to email and counts the rest", () => {
    expect(sampleText(p)).toBe("A, b@x and 10 more");
    expect(sampleText({ ...p, matched_count: 2 })).toBe("A, b@x");
    expect(sampleText({ ...p, sample: [] })).toBe("");
  });
  test("confirm only for required with people to enroll", () => {
    expect(needsEnrollConfirm(draft({ mode: "required" }), p)).toBe(true);
    expect(needsEnrollConfirm(draft({ mode: "optin" }), p)).toBe(false);
    expect(needsEnrollConfirm(draft({ mode: "required" }), { ...p, would_enroll: 0 })).toBe(false);
    expect(needsEnrollConfirm(draft({ mode: "required" }), null)).toBe(false);
    expect(confirmText(p)).toBe("Enroll 5 people now?");
    expect(confirmText({ ...p, would_enroll: 1 })).toBe("Enroll 1 person now?");
  });
  test("resultText", () => {
    expect(resultText({ enrolled: 3, memberships_added: 4, memberships_removed: 0, matched_count: 4 }))
      .toBe("Audience saved: 4 matched, 3 enrolled, 4 given access.");
  });
});

describe("normalizeOptions", () => {
  test("accepts object and string forms", () => {
    const o = normalizeOptions({
      departments: [{ key: "maal", name: "Maal", aka: [] }, "tarbiyyat"],
      levels: [{ key: "local", label: "Local" }],
      roles: [{ key: "naib_sadr", title: "Naib Sadr", plural: "x" }],
    });
    expect(o.departments).toEqual([{ key: "maal", label: "Maal" }, { key: "tarbiyyat", label: "Tarbiyyat" }]);
    expect(o.levels).toEqual([{ key: "local", label: "Local" }]);
    expect(o.roles).toEqual([{ key: "naib_sadr", label: "Naib Sadr" }]);
    expect(normalizeOptions(null)).toEqual({ departments: [], levels: [], roles: [] });
  });
});

describe("mkaCourseAudienceEnabled", () => {
  const VAR = "NEXT_PUBLIC_MKA_COURSE_AUDIENCE_ENABLED";
  const saved = process.env[VAR];
  const hadWindow = "window" in globalThis;
  afterEach(() => {
    saved === undefined ? delete process.env[VAR] : (process.env[VAR] = saved);
    if (!hadWindow) delete globalThis.window; else delete globalThis.window.__RUNTIME_CONFIG__;
  });
  test("server: only '1' enables", () => {
    if (hadWindow) return;
    delete process.env[VAR]; expect(mkaCourseAudienceEnabled()).toBe(false);
    process.env[VAR] = "1"; expect(mkaCourseAudienceEnabled()).toBe(true);
    process.env[VAR] = "true"; expect(mkaCourseAudienceEnabled()).toBe(false);
  });
  test("client: runtime config wins both ways", () => {
    globalThis.window = globalThis.window ?? {};
    process.env[VAR] = "0"; window.__RUNTIME_CONFIG__ = { [VAR]: "1" };
    expect(mkaCourseAudienceEnabled()).toBe(true);
    process.env[VAR] = "1"; window.__RUNTIME_CONFIG__ = { [VAR]: "0" };
    expect(mkaCourseAudienceEnabled()).toBe(false);
  });
});
