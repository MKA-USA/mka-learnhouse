import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

// Upgrade guard (spec B6 / contracts section 4). TipTap runs with enableContentCheck:false, so any editor
// instance that loads activity content without the MKA nodes renders the WHOLE lesson blank. After an upstream
// pull, a NEW editor site would silently break audience lessons: this test fails until it is hooked.
const WEB = new URL("..", import.meta.url).pathname;

// A "site" is a source file that builds a TipTap editor/schema. `extensions: [` alone is too common a phrase
// (file-type lists), so a file only counts when it also imports from @tiptap.
const SITE = /useEditor\(|new Editor\(|extensions:\s*\[|\bEditorProvider\b|generateHTML|generateJSON|getSchema\(/;
const TIPTAP = /from\s+['"]@tiptap\//;
const SKIP_DIRS = new Set(["node_modules", ".next", ".git", "tests", "public", "locales", "coverage", "dist", "out"]);

// Sites that never load activity JSON (verified in the audience-web-core seam report).
const ALLOW = new Set([
  "components/Objects/Communities/DiscussionEditor.tsx",
  "components/Objects/Communities/DiscussionContent.tsx",
  "components/Dashboard/Boards/BoardCanvas.tsx",
]);
const ALLOW_PREFIX = ["components/mka/"];
const REQUIRED = [
  "components/Objects/Editor/Editor.tsx",
  "components/Objects/Activities/DynamicCanva/DynamicCanva.tsx",
  "components/Objects/Editor/EditorPreview.tsx",
];

const stripComments = (src) => src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

/** A real, non-comment import of mkaEditorExtensions AND a spread call of it. */
export function hasHook(src) {
  const code = stripComments(src);
  const imported = /import\s*\{[^}]*\bmkaEditorExtensions\b[^}]*\}\s*from\s*['"][^'"]*mka\/editor['"]/.test(code);
  const spread = /\.\.\.\s*mkaEditorExtensions\(/.test(code);
  return imported && spread;
}

export function violations(files) {
  return files
    .filter((f) => !ALLOW.has(f.path) && !ALLOW_PREFIX.some((p) => f.path.startsWith(p)))
    .filter((f) => {
      const code = stripComments(f.src);
      return SITE.test(code) && TIPTAP.test(code);
    })
    .filter((f) => !hasHook(f.src))
    .map((f) => f.path);
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (SKIP_DIRS.has(name)) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(ts|tsx|js|jsx|mjs)$/.test(name) && !name.endsWith(".d.ts")) out.push(p);
  }
  return out;
}

const rel = (p) => relative(WEB, p).split(sep).join("/");
const files = walk(WEB).map((p) => ({ path: rel(p), src: readFileSync(p, "utf8") }));

describe("MKA editor hook guard", () => {
  test("scans every source dir of apps/web (not only components and app)", () => {
    const tops = new Set(files.map((f) => f.path.split("/")[0]));
    for (const d of ["components", "app", "lib", "services", "hooks"]) expect(tops.has(d)).toBe(true);
    expect(files.some((f) => f.path.startsWith("tests/"))).toBe(false);
  });

  test("the scan finds the known editor sites (guards the guard)", () => {
    const sites = files.filter((f) => !f.path.startsWith("components/mka/") && SITE.test(stripComments(f.src)) && TIPTAP.test(f.src)).map((f) => f.path);
    for (const p of [...ALLOW, ...REQUIRED]) expect(sites).toContain(p);
  });

  test("every non-allow-listed TipTap site registers the MKA nodes", () => {
    expect(violations(files)).toEqual([]);
  });

  for (const path of REQUIRED) {
    test(`W hook present: ${path}`, () => {
      const src = readFileSync(join(WEB, path), "utf8");
      expect(hasHook(src)).toBe(true);
      // Every hook line carries the fork marker so an upstream merge conflict is easy to spot.
      for (const line of src.split("\n").filter((l) => l.includes("mkaEditorExtensions"))) {
        expect(line).toContain("// MKA fork");
      }
    });
  }
});

describe("hook guard rules (synthetic files)", () => {
  const editor = (extra = "") => `import { useEditor } from '@tiptap/react'\n${extra}\nconst e = useEditor({ extensions: [A] })\n`;
  const HOOKED = "import { mkaEditorExtensions } from '@components/mka/editor'\nconst x = [...mkaEditorExtensions({ editable: false })]";

  test("a new site in ee/ or lib/ without the hook is a violation", () => {
    expect(violations([{ path: "ee/foo/Viewer.tsx", src: editor() }])).toEqual(["ee/foo/Viewer.tsx"]);
    expect(violations([{ path: "lib/x.ts", src: editor() }])).toEqual(["lib/x.ts"]);
  });
  test("EditorProvider / generateHTML / generateJSON / getSchema / new Editor sites count", () => {
    for (const body of ["<EditorProvider extensions={x} />", "generateHTML(j, x)", "generateJSON(h, x)", "getSchema(x)", "new Editor({})"]) {
      const src = `import { x } from '@tiptap/react'\n${body}`;
      expect(violations([{ path: "ee/a.tsx", src }])).toEqual(["ee/a.tsx"]);
    }
  });
  test("a hooked site passes", () => {
    expect(violations([{ path: "ee/foo/Viewer.tsx", src: editor(HOOKED) }])).toEqual([]);
  });
  test("a comment that merely mentions the hook does not count", () => {
    const src = editor("// TODO: mkaEditorExtensions(...) // MKA fork\n/* ...mkaEditorExtensions( */");
    expect(violations([{ path: "ee/foo/Viewer.tsx", src }])).toEqual(["ee/foo/Viewer.tsx"]);
  });
  test("importing without spreading (or spreading without importing) does not count", () => {
    expect(hasHook("import { mkaEditorExtensions } from '@components/mka/editor'\nconst a = 1")).toBe(false);
    expect(hasHook("const a = [...mkaEditorExtensions({})]")).toBe(false);
  });
  test("an import from the wrong module does not count", () => {
    expect(hasHook("import { mkaEditorExtensions } from './other'\n[...mkaEditorExtensions({})]")).toBe(false);
  });
  test("files that only say 'extensions: [' without TipTap are not sites", () => {
    expect(violations([{ path: "lib/file-validation.ts", src: "const rules = { extensions: ['.png'] }\nextensions: [" }])).toEqual([]);
  });
  test("allow-list and components/mka are exempt", () => {
    expect(violations([{ path: "components/Objects/Communities/DiscussionEditor.tsx", src: editor() }])).toEqual([]);
    expect(violations([{ path: "components/mka/editor/x.ts", src: editor() }])).toEqual([]);
  });
});
