import { describe, expect, test } from "bun:test";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { ruleHash } from "../services/mka/attributes.ts";

// Learner viewers (DynamicCanva, EditorPreview) import mkaEditorExtensions. Author chrome (picker, header, bar,
// preview menu, popover/sheet UI) must be reachable only through dynamic import(), so it never ships to learners.
const WEB = new URL("..", import.meta.url).pathname;
const EXTS = ["", ".ts", ".tsx", "/index.ts", "/index.tsx"];

function resolveImport(from, spec) {
  let base;
  if (spec.startsWith("@components/")) base = join(WEB, "components", spec.slice("@components/".length));
  else if (spec.startsWith("@services/")) base = join(WEB, "services", spec.slice("@services/".length));
  else if (spec.startsWith(".")) base = resolve(dirname(from), spec);
  else return null;
  for (const e of EXTS) if (existsSync(base + e) && !base.endsWith("/") && /\.\w+$/.test(base + e)) return base + e;
  return null;
}

function staticClosure(entry) {
  const seen = new Set();
  const stack = [entry];
  while (stack.length) {
    const f = stack.pop();
    if (seen.has(f)) continue;
    seen.add(f);
    const src = readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    // static imports and re-exports only; `import('./x')` is a dynamic import and is deliberately not followed
    // `import type` / `export type` are erased at build time and ship nothing
    for (const m of src.matchAll(/^\s*(?:import|export)\s(?!type\s)[^;'"]*?from\s*['"]([^'"]+)['"]/gm)) {
      const r = resolveImport(f, m[1]);
      if (r) stack.push(r);
    }
    for (const m of src.matchAll(/^\s*import\s*['"]([^'"]+)['"]/gm)) {
      const r = resolveImport(f, m[1]);
      if (r) stack.push(r);
    }
  }
  return [...seen].map((p) => p.slice(WEB.length));
}

describe("learner bundle", () => {
  const closure = staticClosure(join(WEB, "components/mka/editor/index.ts"));

  test("the static import graph of mkaEditorExtensions reaches the node views and evaluator", () => {
    for (const p of ["components/mka/editor/AudienceNode.ts", "components/mka/editor/AudienceView.tsx", "components/mka/audience/evaluate.ts", "components/mka/editor/learnerFilter.ts"]) {
      expect(closure).toContain(p);
    }
  });

  test("author chrome is NOT statically reachable (picker, header, bar, preview menu, popover UI, slash menu)", () => {
    for (const p of [
      "components/mka/editor/AudiencePicker.tsx",
      "components/mka/editor/AudienceHeader.tsx",
      "components/mka/editor/AudienceBar.tsx",
      "components/mka/editor/PreviewMenu.tsx",
      "components/mka/editor/audience-ui.tsx",
      "components/mka/editor/AuthorSection.tsx",
      "components/mka/editor/SectionNotices.tsx",
      "components/mka/editor/slash.tsx",
      "components/ui/popover.tsx",
    ]) {
      expect(closure).not.toContain(p);
    }
  });

  test("the closure walker itself sees static imports (guards the guard)", () => {
    const authorClosure = staticClosure(join(WEB, "components/mka/editor/AuthorSection.tsx"));
    expect(authorClosure).toContain("components/mka/editor/AudiencePicker.tsx");
  });
});

describe("ruleHash", () => {
  test("ignores key order and ONLY the top-level label", () => {
    const a = { v: 1, mode: "show", groups: [{ level: ["local"], department: ["tabligh"] }], label: "x" };
    const b = { label: "y", groups: [{ department: ["tabligh"], level: ["local"] }], mode: "show", v: 1 };
    expect(ruleHash(a)).toBe(ruleHash(b));
  });
  test("a nested `label` key is part of the rule and changes the hash", () => {
    const base = { v: 1, mode: "show", groups: [{ level: ["local"] }] };
    const nested = { v: 1, mode: "show", groups: [{ level: ["local"], label: ["x"] }] };
    expect(ruleHash(base)).not.toBe(ruleHash(nested));
  });
});
