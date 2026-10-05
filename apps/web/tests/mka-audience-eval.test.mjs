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
