import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

// Upgrade guard (spec B6 / contracts section 4). TipTap runs with enableContentCheck:false, so any editor
// instance that loads activity content without the MKA nodes renders the WHOLE lesson blank. After an upstream
// pull, a NEW editor site would silently break audience lessons: this test fails until it is hooked.
const WEB = new URL("..", import.meta.url).pathname;

const SITE = /useEditor\(|new Editor\(|extensions:\s*\[/;
const HOOK = "mkaEditorExtensions(";

// Sites that never load activity JSON (verified in the audience-web-core seam report).
const ALLOW = new Set([
  "components/Objects/Communities/DiscussionEditor.tsx",
  "components/Objects/Communities/DiscussionContent.tsx",
  "components/Dashboard/Boards/BoardCanvas.tsx",
]);
const REQUIRED = [
  "components/Objects/Editor/Editor.tsx",
  "components/Objects/Activities/DynamicCanva/DynamicCanva.tsx",
  "components/Objects/Editor/EditorPreview.tsx",
];

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === ".next") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(ts|tsx|js|jsx|mjs)$/.test(name)) out.push(p);
  }
  return out;
}

const rel = (p) => relative(WEB, p).split(sep).join("/");
const sites = [...walk(join(WEB, "components")), ...walk(join(WEB, "app"))]
  .map((p) => ({ path: rel(p), src: readFileSync(p, "utf8") }))
  .filter((f) => !f.path.startsWith("components/mka/") && SITE.test(f.src));

describe("MKA editor hook guard", () => {
  test("the scan finds the known editor sites (guards the guard)", () => {
    const paths = sites.map((s) => s.path);
    for (const p of [...ALLOW, ...REQUIRED]) expect(paths).toContain(p);
  });

  test("every non-allow-listed TipTap site registers the MKA nodes", () => {
    const missing = sites.filter((s) => !ALLOW.has(s.path) && !s.src.includes(HOOK)).map((s) => s.path);
    expect(missing).toEqual([]);
  });

  for (const path of REQUIRED) {
    test(`W hook present: ${path}`, () => {
      const src = readFileSync(join(WEB, path), "utf8");
      expect(src).toContain(HOOK);
      expect(src).toContain("from '@components/mka/editor'");
      // Both lines carry the fork marker so an upstream merge conflict is easy to spot.
      for (const line of src.split("\n").filter((l) => l.includes("mkaEditorExtensions"))) {
        expect(line).toContain("// MKA fork");
      }
    });
  }
});
