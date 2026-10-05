import { afterEach, beforeAll, describe, expect, test } from "bun:test";
import { Window } from "happy-dom";

// End-to-end through React: real TipTap editor + EditorContent + the fork's node views, controller and chrome,
// against the mock attributes layer (NEXT_PUBLIC_MKA_AUDIENCE_MOCK). The viewer is chosen with ?mka_viewer= and
// ?mka_admin=1, exactly like the browser dev switches.
const domWindow = new Window({ url: "http://localhost/" });
for (const key of [
  "document", "navigator", "HTMLElement", "Element", "Node", "Text", "DocumentFragment", "MutationObserver",
  "Range", "Selection", "DOMParser", "getComputedStyle", "requestAnimationFrame", "cancelAnimationFrame",
  "CustomEvent", "Event", "KeyboardEvent", "MouseEvent", "InputEvent", "NodeFilter", "DOMException",
  "HTMLInputElement", "ClipboardEvent", "HTMLIFrameElement", "SVGElement", "ResizeObserver", "FocusEvent", "PointerEvent",
]) {
  if (domWindow[key] !== undefined && globalThis[key] === undefined) globalThis[key] = domWindow[key];
}
// Radix dispatches `new CustomEvent(...)` on happy-dom nodes: those must be happy-dom's classes, not Bun's.
for (const key of ["Event", "CustomEvent"]) globalThis[key] = domWindow[key];
globalThis.window = domWindow;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} };

process.env.NEXT_PUBLIC_MKA_AUDIENCE_MOCK = "1";

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
const { EditorContent, useEditor } = await import("@tiptap/react");
const { default: StarterKit } = await import("@tiptap/starter-kit");
const { default: EditorOptionsProvider } = await import("../components/Contexts/Editor/EditorContext.tsx");
const { mkaEditorExtensions } = await import("../components/mka/editor/index.ts");
const { AudienceView } = await import("../components/mka/editor/AudienceView.tsx");
const { getAudienceStore } = await import("../components/mka/editor/store.ts");

const h = React.createElement;
const tick = () => new Promise((r) => setTimeout(r, 0));
const settle = async () => {
  for (let i = 0; i < 6; i++) await act(async () => { await tick(); });
};

const rule = (level, mode = "show") => ({ v: 1, mode, groups: [{ level: [level] }] });
const para = (text) => ({ type: "paragraph", content: text ? [{ type: "text", text }] : [] });
const section = (id, text, r) => ({ type: "mkaAudience", attrs: { id, rule: r }, content: [para(text)] });
const doc = (...content) => ({ type: "doc", content });

let current = null;
function Harness({ content, editable, onEditor }) {
  const editor = useEditor({
    immediatelyRender: false,
    editable,
    extensions: [StarterKit.configure({ trailingNode: false }), ...mkaEditorExtensions({ editable, activity: { org_id: 1 }, courseUuid: "course_x" })],
    content,
  });
  React.useEffect(() => { if (editor) onEditor?.(editor); }, [editor]);
  return h(EditorOptionsProvider, { options: { isEditable: editable } }, h(EditorContent, { editor }));
}

async function mount(content, { editable = false, search = "", flag = "0" } = {}) {
  domWindow.happyDOM.setURL(`http://localhost/${search}`);
  process.env.NEXT_PUBLIC_MKA_AUDIENCE_ENABLED = flag;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let editor = null;
  await act(async () => {
    root.render(h(QueryClientProvider, { client: qc }, h(Harness, { content, editable, onEditor: (e) => (editor = e) })));
  });
  current = { root, container };
  return { container, editor: () => editor, root };
}

afterEach(async () => {
  if (current) {
    await act(async () => current.root.unmount());
    current.container.remove();
    current = null;
  }
});

const content = doc(
  para("PUBLIC-TEXT"),
  section("a", "LOCAL-ONLY-TEXT", rule("local")),
  section("b", "REGIONAL-ONLY-TEXT", rule("regional")),
  section("c", "NOT-LOCAL-TEXT", rule("local", "hide")),
);

describe("learner (default mock viewer: local Nazim Tabligh)", () => {
  test("no flash: while /me is loading no section content is in the DOM", async () => {
    const { container } = await mount(content);
    // mount() resolved the first render only; the mocked /me has not answered yet
    expect(container.textContent).toContain("PUBLIC-TEXT");
    for (const secret of ["LOCAL-ONLY-TEXT", "REGIONAL-ONLY-TEXT", "NOT-LOCAL-TEXT"]) {
      expect(container.innerHTML).not.toContain(secret);
    }
  });

  test("match shows content with no chrome; non-match content is NOT in the document DOM", async () => {
    const { container } = await mount(content);
    await settle();
    expect(container.textContent).toContain("PUBLIC-TEXT");
    expect(container.textContent).toContain("LOCAL-ONLY-TEXT");
    expect(container.innerHTML).not.toContain("REGIONAL-ONLY-TEXT"); // not merely display:none
    expect(container.innerHTML).not.toContain("NOT-LOCAL-TEXT");
    expect(container.textContent).not.toContain("Visible to");
    expect(container.textContent).not.toContain("Hidden for this viewer");
    expect(container.querySelector('[data-testid="mka-audience-bar"]')).toBeNull();
  });
});

describe("learner notes", () => {
  test("unrecognized viewer: tailored-by-role note appears once", async () => {
    const { container } = await mount(content, { search: "?mka_viewer=unrecognized-account" });
    await settle();
    expect(container.querySelectorAll('[data-testid="mka-note-unrecognized"]').length).toBe(1);
    expect(container.textContent).toContain("We couldn't recognise your role");
    expect(container.innerHTML).not.toContain("LOCAL-ONLY-TEXT");
    expect(container.textContent).toContain("NOT-LOCAL-TEXT"); // hide-from-local shows for unknown viewers
  });

  test("empty lesson note when everything is hidden", async () => {
    const onlyRegional = doc(para(""), section("b", "REGIONAL-ONLY-TEXT", rule("regional")));
    const { container } = await mount(onlyRegional);
    await settle();
    expect(container.querySelector('[data-testid="mka-note-empty"]')).not.toBeNull();
    expect(container.textContent).toContain("Nothing in this lesson applies to your role");
    expect(container.innerHTML).not.toContain("REGIONAL-ONLY-TEXT");
  });
});

describe("can_view_all viewer on the learner page", () => {
  test("sees everything with read-only 'Visible to' badges and the bar defaults to Everything", async () => {
    const { container } = await mount(content, { search: "?mka_admin=1", flag: "1" });
    await settle();
    for (const t of ["LOCAL-ONLY-TEXT", "REGIONAL-ONLY-TEXT", "NOT-LOCAL-TEXT"]) expect(container.textContent).toContain(t);
    expect(container.querySelectorAll('[data-testid="mka-audience-badge"]').length).toBe(3);
    expect(container.querySelector('[data-testid="mka-audience-header"]')).toBeNull(); // read-only: no author header
    const bar = container.querySelector('[data-testid="mka-audience-bar"]');
    expect(bar).not.toBeNull();
    expect(bar.textContent).toContain("3 audience sections");
  });

  test("bar is an authoring entry point: hidden when the feature flag is off", async () => {
    const { container } = await mount(content, { search: "?mka_admin=1", flag: "0" });
    await settle();
    expect(container.querySelector('[data-testid="mka-audience-bar"]')).toBeNull();
    expect(container.textContent).toContain("REGIONAL-ONLY-TEXT"); // evaluation itself is not flag-gated
  });

  test("preview as a persona: non-match becomes a placeholder, content detached", async () => {
    const m = await mount(content, { search: "?mka_admin=1", flag: "1" });
    await settle();
    await act(async () => {
      getAudienceStore(m.editor()).set({
        view: { kind: "persona", label: "Regional Qaid · Northeast", attributes: { status: "matched", is_officeholder: true, level: "regional", department: null, role: "regional_qaid", role_title: "Regional Qaid", majlis: null, region: "Northeast" } },
      });
    });
    await settle();
    expect(m.container.textContent).toContain("REGIONAL-ONLY-TEXT");
    expect(m.container.innerHTML).not.toContain("LOCAL-ONLY-TEXT");
    expect(m.container.textContent).toContain("Hidden for this viewer · Visible to");
    expect(m.container.querySelectorAll('[data-testid="mka-audience-placeholder"]').length).toBe(1);
  });
});

describe("authoring", () => {
  test("editable editor: every section shows its content and the author header", async () => {
    const m = await mount(content, { editable: true, flag: "1" });
    await settle();
    for (const t of ["LOCAL-ONLY-TEXT", "REGIONAL-ONLY-TEXT", "NOT-LOCAL-TEXT"]) expect(m.container.textContent).toContain(t);
    expect(m.container.querySelectorAll('[data-testid="mka-audience-header"]').length).toBe(3);
    expect(m.container.querySelector('[data-testid="mka-audience-bar"]')).not.toBeNull();
    expect(m.editor().isEditable).toBe(true);
  });

  test("preview-as makes the editor read-only and Everything restores it, without touching content", async () => {
    const m = await mount(content, { editable: true, flag: "1" });
    await settle();
    const before = JSON.stringify(m.editor().getJSON());
    await act(async () => getAudienceStore(m.editor()).set({ view: { kind: "self" } }));
    await settle();
    expect(m.editor().isEditable).toBe(false);
    expect(m.container.innerHTML).not.toContain("REGIONAL-ONLY-TEXT");
    expect(m.container.textContent).toContain("Hidden for this viewer");
    await act(async () => getAudienceStore(m.editor()).set({ view: { kind: "author" } }));
    await settle();
    expect(m.editor().isEditable).toBe(true);
    expect(m.container.textContent).toContain("REGIONAL-ONLY-TEXT");
    expect(JSON.stringify(m.editor().getJSON())).toBe(before);
  });

  test("a newly inserted section opens its picker immediately", async () => {
    const m = await mount(doc(para("hello")), { editable: true, flag: "1" });
    await settle();
    await act(async () => { m.editor().commands.setTextSelection(2); m.editor().commands.setMkaAudience(); });
    await settle();
    expect(document.body.querySelector('[data-testid="mka-audience-picker"]')).not.toBeNull();
  });

  test("rule written by a newer editor is read-only for authors (no Edit)", async () => {
    const newer = doc(section("n", "NEWER-TEXT", { v: 2, mode: "show", groups: [{}] }));
    const m = await mount(newer, { editable: true, flag: "1" });
    await settle();
    expect(m.container.textContent).toContain("NEWER-TEXT");
    const header = m.container.querySelector('[data-testid="mka-audience-header"]');
    expect(header.textContent).toContain("newer_version");
    expect([...header.querySelectorAll("button")].some((b) => b.textContent === "Edit")).toBe(false);
  });
});

describe("inline fields", () => {
  const fieldDoc = doc({ type: "paragraph", content: [{ type: "text", text: "In " }, { type: "mkaViewerField", attrs: { field: "majlis", fallback: "your Majlis" } }, { type: "text", text: " go." }] });
  test("learner sees their value; unrecognized learner sees the fallback; author sees a chip", async () => {
    let m = await mount(fieldDoc);
    await settle();
    expect(m.container.textContent).toContain("In Albany go.");
    await act(async () => m.root.unmount()); m.container.remove(); current = null;

    m = await mount(fieldDoc, { search: "?mka_viewer=unrecognized-account" });
    await settle();
    expect(m.container.textContent).toContain("In your Majlis go.");
    await act(async () => m.root.unmount()); m.container.remove(); current = null;

    m = await mount(fieldDoc, { editable: true });
    await settle();
    expect(m.container.textContent).toContain("‹Majlis›");
  });
});

describe("failure policy", () => {
  const exploding = { type: { name: "mkaAudience" }, get attrs() { throw new Error("boom"); }, childCount: 0, nodeSize: 2 };
  const run = async (editable) => {
    const modes = [];
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const qc = new QueryClient();
    const origError = console.error;
    console.error = () => {};
    await act(async () => {
      root.render(h(QueryClientProvider, { client: qc }, h(AudienceView, {
        nodeView: { setMode: (m) => modes.push(m) },
        node: exploding,
        editor: { storage: {} },
        getPos: () => 0,
        options: { editable, activity: { org_id: 1 } },
      })));
    });
    console.error = origError;
    await act(async () => root.unmount());
    container.remove();
    return modes;
  };
  test("a crash in the controller shows the content plainly for authoring editors", async () => {
    expect((await run(true)).at(-1)).toBe("content");
  });
  test("a crash in the controller shows NOTHING everywhere else (fail-safe hide)", async () => {
    expect((await run(false)).at(-1)).toBe("hidden");
  });
});
