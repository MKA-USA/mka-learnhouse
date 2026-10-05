import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { validateRule, evaluateRule } from "../components/mka/audience/evaluate.ts";

const vectors = JSON.parse(
  readFileSync(new URL("../../api/src/tests/services/mka/vectors/audience_vectors.json", import.meta.url), "utf8"),
);

describe("shared audience vectors: evaluate", () => {
  for (const c of vectors.evaluate) {
    test(c.name, () => {
      expect(c.viewer in vectors.viewers).toBe(true);
      expect(evaluateRule(c.rule, vectors.viewers[c.viewer])).toBe(c.expect);
    });
  }
});

describe("shared audience vectors: validate", () => {
  for (const c of vectors.validate) {
    test(c.name, () => {
      const res = validateRule(c.rule);
      expect(res.ok).toBe(c.ok);
      if (c.ok && c.normalized !== undefined) expect(res.rule).toEqual(c.normalized);
    });
  }
});

describe("parity hardening", () => {
  const showAny = { v: 1, mode: "show", groups: [{ officeholder: false }] }; // matches any signed-in viewer
  const hideAny = { v: 1, mode: "hide", groups: [{ officeholder: false }] };
  test("a non-object viewer is anonymous (NULL_VIEWER), not signed in", () => {
    for (const bad of [5, "matched", true, false, [], ["matched"], 0, ""]) {
      expect(evaluateRule(showAny, bad)).toBe(false);
      expect(evaluateRule(hideAny, bad)).toBe(true);
    }
    // a real object with an unknown status is still a signed-in viewer
    expect(evaluateRule(showAny, { status: "weird" })).toBe(true);
  });
  test("v must be a SAFE integer", () => {
    const rule = (v) => ({ v, mode: "show", groups: [{}] });
    expect(validateRule(rule(9007199254740991)).ok).toBe(true);
    expect(validateRule(rule(9007199254740993)).ok).toBe(false);
    expect(validateRule(rule(1e300)).ok).toBe(false);
  });
});
