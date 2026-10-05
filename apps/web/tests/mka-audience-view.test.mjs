import { afterEach, describe, expect, test } from "bun:test";
import { Window } from "happy-dom";

// End-to-end through React: real TipTap editor + EditorContent + the fork's node views, controller and chrome,
// against the mock attributes layer (NEXT_PUBLIC_MKA_AUDIENCE_MOCK). The viewer is chosen with ?mka_viewer= and
// ?mka_admin=1, exactly like the browser dev switches.
// Reuse the DOM installed by tests/setup/dom.mjs (bunfig preload) so `document` and `window` are one happy-dom window.
const domWindow = globalThis.window ?? new Window({ url: "http://localhost/" });
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
const { NoTextInput } = await import("../components/Objects/Editor/Extensions/NoTextInput/NoTextInput");
const { SessionContext } = await import("../components/Contexts/LHSessionContext.tsx");
const { default: EditorOptionsProvider } = await import("../components/Contexts/Editor/EditorContext.tsx");
const { mkaEditorExtensions } = await import("../components/mka/editor/index.ts");
const { AudienceView } = await import("../components/mka/editor/AudienceView.tsx");
const { getAudienceStore } = await import("../components/mka/editor/store.ts");
const { undoDepth } = await import("@tiptap/pm/history");
const { closeHistory } = await import("@tiptap/pm/history");
const { useMkaViewer, mkaAttributeKeys } = await import("../services/mka/attributes.ts");

const h = React.createElement;
const tick = () => new Promise((r) => setTimeout(r, 0));
// Lazy author chrome (React.lazy) resolves through real module loading, whose duration varies with machine load.
// Preload those modules so lazy() resolves from the module cache, and settle by waiting for the DOM to be stable
// instead of for a fixed number of ticks.
await Promise.all([
  import("../components/mka/editor/AuthorSection.tsx"),
  import("../components/mka/editor/SectionNotices.tsx"),
  import("../components/mka/editor/AudienceBar.tsx"),
  import("../services/mka/attributes.mock.ts"),
]);
const snapshot = () => document.body.innerHTML.length + ":" + document.body.textContent.length;
const settle = async () => {
  let last = null;
  let stable = 0;
  for (let i = 0; i < 400 && stable < 8; i++) {
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
    const now = snapshot();
    stable = now === last ? stable + 1 : 0;
    last = now;
  }
};

const rule = (level, mode = "show") => ({ v: 1, mode, groups: [{ level: [level] }] });
const para = (text) => ({ type: "paragraph", content: text ? [{ type: "text", text }] : [] });
const section = (id, text, r) => ({ type: "mkaAudience", attrs: { id, rule: r }, content: [para(text)] });
const doc = (...content) => ({ type: "doc", content });

let current = null;
function Harness({ content, editable, onEditor, allowDocEdits }) {
  const editor = useEditor({
    immediatelyRender: false,
    editable,
    extensions: [StarterKit.configure({ trailingNode: false }), ...(editable || allowDocEdits ? [] : [NoTextInput]), ...mkaEditorExtensions({ editable, activity: { org_id: 1 }, courseUuid: "course_x" })],
    content,
  });
  React.useEffect(() => { if (editor) onEditor?.(editor); }, [editor]);
  return h(EditorOptionsProvider, { options: { isEditable: editable } }, h(EditorContent, { editor }));
}

const realFetch = globalThis.fetch;
const mockEnv = process.env.NEXT_PUBLIC_MKA_AUDIENCE_MOCK;
async function mount(content, { editable = false, search = "", flag = "0", pendingMe = null, allowDocEdits = false } = {}) {
  domWindow.happyDOM.setURL(`http://localhost/${search}`);
  process.env.NEXT_PUBLIC_MKA_AUDIENCE_ENABLED = flag;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let editor = null;
  await act(async () => {
    let tree = h(QueryClientProvider, { client: qc }, h(Harness, { content, editable, allowDocEdits, onEditor: (e) => (editor = e) }));
    if (pendingMe) {
      // Real fetch path with a /me response the TEST controls, so "while loading" is deterministic.
      process.env.NEXT_PUBLIC_MKA_AUDIENCE_MOCK = "";
      globalThis.fetch = (url) => (String(url).includes("/me") ? pendingMe.promise : Promise.resolve({ ok: false, status: 404, json: async () => ({}) }));
      tree = h(SessionContext.Provider, { value: { status: "authenticated", data: { tokens: { access_token: "t" } } } }, tree);
    }
    root.render(tree);
  });
  current = { root, container, qc };
  return { container, editor: () => editor, root, qc };
}

afterEach(async () => {
  globalThis.fetch = realFetch;
  process.env.NEXT_PUBLIC_MKA_AUDIENCE_MOCK = mockEnv;
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
  test("no flash: while /me is loading no section content is in the DOM; it appears when /me answers", async () => {
    let resolveMe;
    const pendingMe = { promise: new Promise((r) => (resolveMe = r)) };
    const { container } = await mount(content, { pendingMe });
    await settle(); // as long as it takes: /me is still pending
    expect(container.textContent).toContain("PUBLIC-TEXT");
    for (const secret of ["LOCAL-ONLY-TEXT", "REGIONAL-ONLY-TEXT", "NOT-LOCAL-TEXT"]) {
      expect(container.innerHTML).not.toContain(secret);
    }
    await act(async () => {
      resolveMe({
        ok: true,
        status: 200,
        json: async () => ({
          attributes: { status: "matched", is_officeholder: true, level: "local", department: null, role: "qaid", role_title: "Qaid", majlis: "Houston", region: "Gulf" },
          stale: false, can_view_all: false, rules_version: "x",
        }),
      });
    });
    await settle();
    expect(container.textContent).toContain("LOCAL-ONLY-TEXT");
    expect(container.innerHTML).not.toContain("REGIONAL-ONLY-TEXT");
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
    expect(container.querySelector('[aria-label="Audience preview"]')).toBeNull();
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
    expect((container.textContent.match(/you can see this because of your role/g) ?? []).length).toBe(3);
    expect(container.querySelector('button[aria-label="Collapse section"]')).toBeNull(); // read-only: no author header
    const bar = container.querySelector('[aria-label="Audience preview"]');
    expect(bar).not.toBeNull();
    expect(bar.textContent).toContain("3 audience sections");
  });

  test("bar is an authoring entry point: hidden when the feature flag is off", async () => {
    const { container } = await mount(content, { search: "?mka_admin=1", flag: "0" });
    await settle();
    expect(container.querySelector('[aria-label="Audience preview"]')).toBeNull();
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
    expect((m.container.textContent.match(/Hidden for this viewer/g) ?? []).length).toBe(1);
  });
});

describe("authoring", () => {
  test("editable editor: every section shows its content and the author header", async () => {
    const m = await mount(content, { editable: true, flag: "1" });
    await settle();
    for (const t of ["LOCAL-ONLY-TEXT", "REGIONAL-ONLY-TEXT", "NOT-LOCAL-TEXT"]) expect(m.container.textContent).toContain(t);
    expect(m.container.querySelectorAll('button[aria-label="Collapse section"]').length).toBe(3);
    expect(m.container.querySelector('[aria-label="Audience preview"]')).not.toBeNull();
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
    expect(document.body.querySelector('[aria-label="Who should see this section?"]')).not.toBeNull();
  });

  test("rule written by a newer editor is read-only for authors (no Edit)", async () => {
    const newer = doc(section("n", "NEWER-TEXT", { v: 2, mode: "show", groups: [{}] }));
    const m = await mount(newer, { editable: true, flag: "1" });
    await settle();
    expect(m.container.textContent).toContain("NEWER-TEXT");
    expect(m.container.textContent).toContain("Made with a newer editor");
    expect([...m.container.querySelectorAll("button")].some((b) => b.textContent.trim() === "Edit")).toBe(false);
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

// ---------------------------------------------------------------------------------------------------------
// Review fixes: hidden content must be out of the editor STATE for learners (H1/H2), preview exit (M3),
// cancel semantics (M4), label source (L9), viewer data precedence (L8).
// ---------------------------------------------------------------------------------------------------------
const heading = (text) => ({ type: "heading", attrs: { level: 2 }, content: [{ type: "text", text }] });
const hsec = (id, r, ...inner) => ({ type: "mkaAudience", attrs: { id, rule: r }, content: inner });
const stateDoc = doc(
  heading("PUBLIC-HEADING"),
  hsec("a", rule("local"), heading("LOCAL-HEADING"), para("LOCAL-BODY")),
  hsec("b", rule("regional"), heading("REGIONAL-HEADING"), para("REGIONAL-BODY")),
);
const tocHeadings = (editor) => {
  const out = [];
  editor.state.doc.descendants((n) => { if (n.type.name.startsWith("heading")) out.push(n.textContent); });
  return out;
};
const selectAllSlice = (editor) => editor.state.doc.slice(0, editor.state.doc.content.size);
const copied = (editor) => editor.view.serializeForClipboard(selectAllSlice(editor));

describe("learner filter: hidden content is not in the editor state", () => {
  test("TOC-style walk, textBetween (AI) and getText exclude the hidden section; matching one is intact", async () => {
    const m = await mount(stateDoc);
    await settle();
    const e = m.editor();
    expect(tocHeadings(e)).toEqual(["PUBLIC-HEADING", "LOCAL-HEADING"]);
    const text = e.state.doc.textBetween(0, e.state.doc.content.size, " ");
    expect(text).toContain("LOCAL-BODY");
    expect(text).not.toContain("REGIONAL");
    expect(e.getText()).not.toContain("REGIONAL");
    // section node and attrs are kept so learner notes still work
    expect(e.getJSON().content.filter((n) => n.type === "mkaAudience").length).toBe(2);
  });

  test("select-all + copy serializes no hidden text and no hidden rule", async () => {
    const m = await mount(stateDoc);
    await settle();
    const { dom, text } = copied(m.editor());
    expect(dom.innerHTML).toContain("LOCAL-BODY");
    for (const hidden of ["REGIONAL", "regional"]) {
      expect(dom.innerHTML).not.toContain(hidden);
      expect(text).not.toContain(hidden);
    }
  });

  test("clipboard safety net on its own: before /me resolves, copy drops every section (fail closed)", async () => {
    const m = await mount(stateDoc);
    // not settled: the filter has not run and nothing is known about the viewer
    const { dom, text } = copied(m.editor());
    expect(dom.innerHTML).not.toContain("data-mka-audience");
    expect(text).not.toContain("LOCAL-BODY");
    expect(text).not.toContain("REGIONAL-BODY");
    expect(dom.innerHTML).toContain("PUBLIC-HEADING");
  });

  test("can_view_all viewers keep the full document (view switching must keep working)", async () => {
    const m = await mount(stateDoc, { search: "?mka_admin=1" });
    await settle();
    expect(tocHeadings(m.editor())).toEqual(["PUBLIC-HEADING", "LOCAL-HEADING", "REGIONAL-HEADING"]);
    expect(copied(m.editor()).text).toContain("REGIONAL-BODY");
  });

  test("a changed viewer re-filters from the ORIGINAL document, not from the already filtered one", async () => {
    const m = await mount(stateDoc);
    await settle();
    expect(tocHeadings(m.editor())).toEqual(["PUBLIC-HEADING", "LOCAL-HEADING"]);
    domWindow.happyDOM.setURL("http://localhost/?mka_viewer=regional-qaid-northeast");
    await act(async () => { await m.qc.invalidateQueries({ queryKey: mkaAttributeKeys.all }); });
    await settle();
    expect(tocHeadings(m.editor())).toEqual(["PUBLIC-HEADING", "REGIONAL-HEADING"]);
    expect(m.editor().state.doc.textContent).toContain("REGIONAL-BODY");
    expect(m.container.innerHTML).not.toContain("LOCAL-BODY");
    // and back: the content that had been stripped is restored from the original
    domWindow.happyDOM.setURL("http://localhost/");
    await act(async () => { await m.qc.invalidateQueries({ queryKey: mkaAttributeKeys.all }); });
    await settle();
    expect(tocHeadings(m.editor())).toEqual(["PUBLIC-HEADING", "LOCAL-HEADING"]);
    expect(m.container.textContent).toContain("LOCAL-BODY");
    expect(m.container.innerHTML).not.toContain("REGIONAL-BODY");
    // the state swap must not re-mount (duplicate) the document-level chrome
    expect(m.container.querySelectorAll(".mka-audience-chrome").length).toBe(1);
  });

  test("filtering is not a user edit: no history entry, and `update` fires once (the TOC's refresh hook)", async () => {
    const m = await mount(stateDoc);
    let updates = 0;
    m.editor().on("update", () => updates++);
    await settle();
    expect(undoDepth(m.editor().state)).toBe(0);
    expect(updates).toBe(1);
  });

  test("learner notes still compute from the filtered document", async () => {
    const onlyRegional = doc(para(""), hsec("b", rule("regional"), heading("REGIONAL-HEADING"), para("REGIONAL-BODY")));
    const { container } = await mount(onlyRegional);
    await settle();
    expect(container.querySelector('[data-testid="mka-note-empty"]')).not.toBeNull();
  });
});

describe("preview exit (M3)", () => {
  test("Preview button is an authoring entry point: absent when the flag is off, present when on", async () => {
    let m = await mount(content, { editable: true, flag: "0" });
    await settle();
    expect([...m.container.querySelectorAll("button")].some((b) => b.textContent.trim() === "Preview")).toBe(false);
    await act(async () => m.root.unmount()); m.container.remove(); current = null;
    m = await mount(content, { editable: true, flag: "1" });
    await settle();
    expect([...m.container.querySelectorAll("button")].some((b) => b.textContent.trim() === "Preview")).toBe(true);
  });

  test("an active preview always shows the bar (with its exit), even with the flag off", async () => {
    const m = await mount(content, { editable: true, flag: "0" });
    await settle();
    expect(m.container.querySelector('[aria-label="Audience preview"]')).toBeNull();
    await act(async () => getAudienceStore(m.editor()).set({ view: { kind: "self" } }));
    await settle();
    expect(m.editor().isEditable).toBe(false);
    expect(m.container.querySelector('[aria-label="Audience preview"]')).not.toBeNull();
    const exit = [...m.container.querySelectorAll("button")].find((b) => /Exit preview/.test(b.textContent));
    expect(exit).toBeTruthy();
    await act(async () => { exit.click(); });
    await settle();
    expect(m.editor().isEditable).toBe(true);
  });
});

describe("cancel semantics (M4)", () => {
  const escape = async () => {
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
    });
    await settle();
  };
  const sections = (e) => e.getJSON().content.filter((n) => n.type === "mkaAudience");

  test("Escape on a NEW inserted section removes it entirely: no stray empty paragraph", async () => {
    const m = await mount(doc(para("hello"), para("world")), { editable: true, flag: "1" });
    await settle();
    const before = m.editor().state.doc.childCount;
    await act(async () => { m.editor().commands.setTextSelection(2); m.editor().commands.setMkaAudience(); });
    await settle();
    expect(sections(m.editor()).length).toBe(1);
    expect(document.body.querySelector('[aria-label="Who should see this section?"]')).not.toBeNull();
    await escape();
    expect(sections(m.editor()).length).toBe(0);
    expect(m.editor().state.doc.childCount).toBe(before);
    expect(m.editor().state.doc.textContent).toBe("helloworld");
  });

  test("Escape on a NEW section that wrapped existing blocks unwraps it and keeps the content", async () => {
    const m = await mount(doc(para("alpha"), para("beta")), { editable: true, flag: "1" });
    await settle();
    await act(async () => { m.editor().commands.setTextSelection({ from: 1, to: 8 }); m.editor().commands.setMkaAudience(); });
    await settle();
    expect(sections(m.editor()).length).toBe(1);
    await escape();
    expect(sections(m.editor()).length).toBe(0);
    expect(m.editor().state.doc.textContent).toBe("alphabeta");
  });

  test("Escape while editing an EXISTING section reverts the live changes", async () => {
    const m = await mount(doc(section("a", "x", rule("local"))), { editable: true, flag: "1" });
    await settle();
    const edit = [...m.container.querySelectorAll("button")].find((b) => b.textContent.trim() === "Edit");
    await act(async () => { edit.click(); });
    await settle();
    await act(async () => { m.editor().commands.updateMkaAudienceRule("a", rule("regional")); });
    await escape();
    expect(sections(m.editor())[0].attrs.rule.groups[0].level).toEqual(["local"]);
  });

  test("Done keeps the changes", async () => {
    const m = await mount(doc(para("hello")), { editable: true, flag: "1" });
    await settle();
    await act(async () => { m.editor().commands.setTextSelection(2); m.editor().commands.setMkaAudience(); });
    await settle();
    const done = [...document.body.querySelectorAll("button")].find((b) => b.textContent.trim() === "Done");
    await act(async () => { done.click(); });
    await settle();
    expect(sections(m.editor()).length).toBe(1);
  });
});

describe("labels (L9) and viewer data precedence (L8)", () => {
  test("header shows the COMPUTED label once options are loaded; the stored label is only a fallback", async () => {
    const stale = { v: 1, mode: "show", groups: [{ level: ["local"] }], label: "STALE-LABEL" };
    const m = await mount(doc(section("a", "x", stale)), { editable: true, flag: "1" });
    await settle();
    expect(m.container.textContent).toContain("Local officeholders");
    expect(m.container.textContent).not.toContain("STALE-LABEL");
  });

  test("read-only badge also uses the computed label", async () => {
    const stale = { v: 1, mode: "show", groups: [{ level: ["local"] }], label: "STALE-LABEL" };
    const m = await mount(doc(section("a", "x", stale)), { search: "?mka_admin=1", flag: "0" });
    await settle();
    expect(m.container.textContent).toContain("Local officeholders");
    expect(m.container.textContent).not.toContain("STALE-LABEL");
  });

  test("useMkaViewer: data wins over a failed background refetch", async () => {
    const { SessionContext } = await import("../components/Contexts/LHSessionContext.tsx");
    const seen = [];
    const Probe = () => { seen.push(useMkaViewer("course_x")); return null; };
    const prevMock = process.env.NEXT_PUBLIC_MKA_AUDIENCE_MOCK;
    const prevFetch = globalThis.fetch;
    process.env.NEXT_PUBLIC_MKA_AUDIENCE_MOCK = ""; // real fetch path, stubbed below
    globalThis.fetch = async () => ({ ok: false, status: 500, json: async () => ({}) });
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(mkaAttributeKeys.me("course_x"), {
      attributes: { status: "matched", is_officeholder: true, level: "local", department: null, role: "qaid", role_title: "Qaid", majlis: "Houston", region: "Gulf" },
      stale: false, can_view_all: false, rules_version: "x",
    });
    const session = { status: "authenticated", data: { tokens: { access_token: "t" } } };
    try {
      await act(async () => {
        root.render(h(SessionContext.Provider, { value: session }, h(QueryClientProvider, { client: qc }, h(Probe))));
      });
      await act(async () => { await qc.refetchQueries({ queryKey: mkaAttributeKeys.me("course_x") }).catch(() => {}); });
      await settle();
      const q = qc.getQueryCache().find({ queryKey: mkaAttributeKeys.me("course_x") });
      expect(q.state.status).toBe("error"); // the background refetch failed ...
      expect(q.state.data).toBeTruthy(); // ... but the data is still there
      expect(seen.at(-1).state).toBe("ready");
      expect(seen.at(-1).viewer.majlis).toBe("Houston");
    } finally {
      globalThis.fetch = prevFetch;
      process.env.NEXT_PUBLIC_MKA_AUDIENCE_MOCK = prevMock;
      await act(async () => root.unmount());
      container.remove();
    }
  });
});

// ---------------------------------------------------------------------------------------------------------
// Undo semantics (A) and original recapture (B)
// ---------------------------------------------------------------------------------------------------------
describe("undo semantics: only Done is an undo step", () => {
  // Simulates real time passing between user actions (history groups merge within 500 ms otherwise).
  const gap = (e) => e.view.dispatch(closeHistory(e.state.tr));
  const click = async (label, root = document.body) => {
    const b = [...root.querySelectorAll("button")].find((x) => x.textContent.trim() === label);
    expect(b).toBeTruthy();
    await act(async () => { b.click(); });
    await settle();
  };
  const escape = async () => {
    await act(async () => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true })); });
    await settle();
  };
  const secs = (e) => e.getJSON().content.filter((n) => n.type === "mkaAudience");
  const insertNew = async (m) => {
    await act(async () => { m.editor().commands.setTextSelection(2); m.editor().commands.setMkaAudience(); });
    await settle();
    gap(m.editor());
  };

  test("Escape on a NEW section: Ctrl+Z afterwards does not resurrect it", async () => {
    const m = await mount(doc(para("hello"), para("world")), { editable: true, flag: "1" });
    await settle();
    await insertNew(m);
    await click("Local officeholders");
    gap(m.editor());
    await escape();
    gap(m.editor());
    expect(secs(m.editor()).length).toBe(0);
    const before = JSON.stringify(m.editor().getJSON());
    for (let i = 0; i < 3; i++) {
      await act(async () => { m.editor().commands.undo(); });
      await settle();
      expect(secs(m.editor()).length).toBe(0); // after EVERY undo, not just the last
      expect(JSON.stringify(m.editor().getJSON())).toBe(before);
    }
  });

  test("Escape while editing an EXISTING section: Ctrl+Z does not re-apply the cancelled rule", async () => {
    const m = await mount(doc(section("a", "x", rule("local"))), { editable: true, flag: "1" });
    await settle();
    await click("Edit", m.container);
    gap(m.editor());
    await click("Regional");
    expect(secs(m.editor())[0].attrs.rule.groups[0].level).toEqual(["local", "regional"]); // live preview
    gap(m.editor());
    await escape();
    gap(m.editor());
    expect(secs(m.editor())[0].attrs.rule.groups[0].level).toEqual(["local"]);
    await act(async () => { m.editor().commands.undo(); });
    await settle();
    expect(secs(m.editor())[0].attrs.rule.groups[0].level).toEqual(["local"]);
  });

  test("Done on an EXISTING section: one Ctrl+Z reverts the whole edit; live steps left no history", async () => {
    const m = await mount(doc(section("a", "x", rule("local"))), { editable: true, flag: "1" });
    await settle();
    await click("Edit", m.container);
    await click("Regional");
    gap(m.editor());
    await click("National");
    gap(m.editor());
    await click("Done");
    expect(secs(m.editor())[0].attrs.rule.groups[0].level).toEqual(["local", "regional", "national"]);
    await act(async () => { m.editor().commands.undo(); });
    await settle();
    expect(secs(m.editor())[0].attrs.rule.groups[0].level).toEqual(["local"]);
    await act(async () => { m.editor().commands.undo(); });
    expect(secs(m.editor())[0].attrs.rule.groups[0].level).toEqual(["local"]); // nothing further to undo
    await act(async () => { m.editor().commands.redo(); });
    expect(secs(m.editor())[0].attrs.rule.groups[0].level).toEqual(["local", "regional", "national"]);
  });

  test("Done on a NEW EMPTY section: cursor stays inside it, so the next keystrokes land in the section", async () => {
    const m = await mount(doc(para("hello"), para("world")), { editable: true, flag: "1" });
    await settle();
    await insertNew(m);
    await click("Local officeholders");
    await click("Done");
    const $from = m.editor().state.selection.$from;
    expect($from.node($from.depth - 1).type.name).toBe("mkaAudience");
    await act(async () => { m.editor().commands.insertContent("TYPED"); });
    const json = m.editor().getJSON();
    expect(secs(m.editor())[0].content.map((n) => n.content?.[0]?.text).join("")).toContain("TYPED");
    expect(JSON.stringify(json.content.filter((n) => n.type !== "mkaAudience"))).not.toContain("TYPED");
  });

  test("Done on a NEW section: ONE Ctrl+Z removes it and leaves no wrapper; redo restores it WITH the final rule", async () => {
    const m = await mount(doc(para("hello"), para("world")), { editable: true, flag: "1" });
    await settle();
    const before = JSON.stringify(m.editor().getJSON());
    await insertNew(m);
    await click("Local officeholders");
    gap(m.editor());
    await click("Done");
    gap(m.editor());
    expect(secs(m.editor())[0].attrs.rule.groups[0].level).toEqual(["local"]);
    await act(async () => { m.editor().commands.undo(); });
    await settle();
    expect(secs(m.editor()).length).toBe(0);
    expect(JSON.stringify(m.editor().getJSON())).toBe(before);
    await act(async () => { m.editor().commands.redo(); });
    await settle();
    expect(secs(m.editor()).length).toBe(1);
    expect(secs(m.editor())[0].attrs.rule.groups[0].level).toEqual(["local"]);
  });

  test("an edit made BEFORE wrapping is still undoable after wrap + pick + Done", async () => {
    const m = await mount(doc(para("hello"), para("world")), { editable: true, flag: "1" });
    await settle();
    await act(async () => { m.editor().commands.insertContentAt(1, "ZZ"); });
    gap(m.editor());
    expect(m.editor().state.doc.textContent).toContain("ZZhello");
    await act(async () => { m.editor().commands.setTextSelection({ from: 1, to: 8 }); m.editor().commands.setMkaAudience(); });
    await settle();
    gap(m.editor());
    await click("Local officeholders");
    gap(m.editor());
    await click("Done");
    gap(m.editor());
    expect(secs(m.editor()).length).toBe(1);
    await act(async () => { m.editor().commands.undo(); });
    await settle();
    expect(secs(m.editor()).length).toBe(0); // undo #1: the section
    expect(m.editor().state.doc.textContent).toContain("ZZhello");
    await act(async () => { m.editor().commands.undo(); });
    await settle();
    expect(m.editor().state.doc.textContent).toBe("helloworld"); // undo #2: the earlier typing survived the wrap
  });

  test("an edit made BEFORE wrapping is still undoable after wrap + Escape", async () => {
    const m = await mount(doc(para("hello"), para("world")), { editable: true, flag: "1" });
    await settle();
    await act(async () => { m.editor().commands.insertContentAt(1, "ZZ"); });
    gap(m.editor());
    await act(async () => { m.editor().commands.setTextSelection({ from: 1, to: 8 }); m.editor().commands.setMkaAudience(); });
    await settle();
    gap(m.editor());
    await click("Local officeholders");
    gap(m.editor());
    await escape();
    gap(m.editor());
    expect(secs(m.editor()).length).toBe(0);
    expect(m.editor().state.doc.textContent).toContain("ZZhello");
    for (let i = 0; i < 4 && m.editor().state.doc.textContent.includes("ZZ"); i++) {
      await act(async () => { m.editor().commands.undo(); });
      await settle();
      expect(secs(m.editor()).length).toBe(0); // never resurrects the cancelled section
    }
    expect(m.editor().state.doc.textContent).toBe("helloworld");
  });
});

describe("original document recapture (B)", () => {
  test("a doc change made AFTER the learner filter never becomes the original: can_view_all then sees full content", async () => {
    const m = await mount(stateDoc, { allowDocEdits: true });
    await settle();
    expect(tocHeadings(m.editor())).toEqual(["PUBLIC-HEADING", "LOCAL-HEADING"]);
    // someone/something edits the (filtered) doc after the swap
    await act(async () => {
      const e = m.editor();
      e.view.dispatch(e.state.tr.insertText("EDIT", 2));
    });
    await settle();
    expect(m.editor().state.doc.textContent).toContain("EDIT");
    // the same viewer is now resolved as can_view_all
    domWindow.happyDOM.setURL("http://localhost/?mka_admin=1");
    await act(async () => { await m.qc.invalidateQueries({ queryKey: mkaAttributeKeys.all }); });
    await settle();
    expect(tocHeadings(m.editor())).toEqual(["PUBLIC-HEADING", "LOCAL-HEADING", "REGIONAL-HEADING"]);
    expect(m.editor().state.doc.textContent).toContain("REGIONAL-BODY");
  });

  test("setContent IS an explicit load: it becomes the new original and is re-filtered", async () => {
    const m = await mount(stateDoc, { allowDocEdits: true });
    await settle();
    const next = doc(para("NEW-PUBLIC"), hsec("c", rule("local"), heading("NEW-LOCAL-HEADING"), para("NEW-LOCAL-BODY")), hsec("d", rule("regional"), heading("NEW-REGIONAL-HEADING"), para("NEW-REGIONAL-BODY")));
    await act(async () => { m.editor().commands.setContent(next); });
    await settle();
    expect(tocHeadings(m.editor())).toEqual(["NEW-LOCAL-HEADING"]);
    expect(m.editor().state.doc.textContent).not.toContain("NEW-REGIONAL-BODY");
    expect(m.container.innerHTML).not.toContain("NEW-REGIONAL-BODY");
  });
});

describe("runtime flag (C): authoring entry points appear when runtime-config.js arrives after hydration", () => {
  const waitFor = async (cond, ms = 2000) => {
    for (let t = 0; t < ms && !cond(); t += 25) await act(async () => { await new Promise((r) => setTimeout(r, 25)); });
    return cond();
  };
  const hasPreview = (c) => [...c.querySelectorAll("button")].some((b) => b.textContent.trim() === "Preview");
  test("flag off at mount, then on via window.__RUNTIME_CONFIG__: the Preview button and bar appear, no editor re-creation", async () => {
    const m = await mount(content, { editable: true, flag: "0" });
    await settle();
    const editorBefore = m.editor();
    expect(hasPreview(m.container)).toBe(false);
    expect(m.container.querySelector('[aria-label="Audience preview"]')).toBeNull();
    window.__RUNTIME_CONFIG__ = { NEXT_PUBLIC_MKA_AUDIENCE_ENABLED: "1" };
    try {
      expect(await waitFor(() => hasPreview(m.container) && !!m.container.querySelector('[aria-label="Audience preview"]'))).toBe(true);
      expect(m.editor()).toBe(editorBefore);
    } finally {
      delete window.__RUNTIME_CONFIG__;
    }
  });
});
