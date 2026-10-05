import { describe, expect, test } from "bun:test";
import { Window } from "happy-dom";

// ProseMirror needs a DOM. happy-dom is already installed alongside the app (see ai-editor-content.test.mjs).
const domWindow = new Window({ url: "http://localhost/" });
for (const key of [
  "document", "navigator", "HTMLElement", "Element", "Node", "Text", "DocumentFragment", "MutationObserver",
  "Range", "Selection", "DOMParser", "getComputedStyle", "requestAnimationFrame", "cancelAnimationFrame",
  "CustomEvent", "Event", "KeyboardEvent", "MouseEvent", "InputEvent", "NodeFilter", "DOMException", "HTMLInputElement", "ClipboardEvent",
]) {
  if (domWindow[key] !== undefined && globalThis[key] === undefined) globalThis[key] = domWindow[key];
}
globalThis.window = domWindow;

const { Editor, getSchema } = await import("@tiptap/core");
const { default: StarterKit } = await import("@tiptap/starter-kit");
const { mkaEditorExtensions } = await import("../components/mka/editor/index.ts");
const { audienceNodeViewFor } = await import("../components/mka/editor/AudienceNodeView.ts");
const { buildFixTransaction } = await import("../components/mka/editor/plugins.ts");
const { getAudienceStore } = await import("../components/mka/editor/store.ts");
const { Node: PMNode } = await import("@tiptap/pm/model");

const showLocal = { v: 1, mode: "show", groups: [{ level: ["local"] }], label: "Local officeholders" };
const para = (text) => ({ type: "paragraph", content: text ? [{ type: "text", text }] : [] });
const section = (id, text, rule = showLocal) => ({ type: "mkaAudience", attrs: { id, rule }, content: [para(text)] });
const docJSON = (...content) => ({ type: "doc", content });

// trailingNode off: it would append an empty paragraph after a trailing section and blur the structure assertions.
const extensions = (opts) => [StarterKit.configure({ trailingNode: false }), ...mkaEditorExtensions(opts)];
const tick = () => new Promise((r) => setTimeout(r, 0));
function make(content, opts = { editable: false }) {
  return new Editor({ extensions: extensions(opts), content, editable: opts.editable });
}
const ids = (editor) => {
  const out = [];
  editor.state.doc.descendants((n) => {
    if (n.type.name === "mkaAudience") out.push(n.attrs.id);
  });
  return out;
};

describe("schema", () => {
  test("mkaEditorExtensions always returns the three nodes, never throws", () => {
    for (const opts of [{ editable: true }, { editable: false }, { editable: false, activity: null }, {}]) {
      const names = mkaEditorExtensions(opts).map((e) => e.name);
      expect(names).toEqual(["mkaAudience", "mkaViewerField", "mkaCounterparts"]);
    }
  });

  test("JSON -> doc -> JSON preserves rule and id (blank-lesson regression: doc is NOT empty)", () => {
    const json = docJSON(para("before"), section("id-1", "secret"), para("after"));
    const schema = getSchema(extensions({ editable: false }));
    const node = PMNode.fromJSON(schema, json);
    expect(node.childCount).toBe(3);
    expect(node.textContent).toContain("secret");
    expect(node.toJSON()).toEqual(json);

    const editor = make(json);
    expect(editor.getJSON()).toEqual(json);
    expect(editor.isEmpty).toBe(false);
    editor.destroy();
  });

  test("HTML round trip keeps rule and id; broken data-rule fails safe as an invalid object", () => {
    const editor = make(docJSON(section("id-9", "x")));
    const html = editor.getHTML();
    expect(html).toContain("data-mka-audience");
    expect(html).toContain('data-id="id-9"');
    editor.commands.setContent(html);
    expect(editor.getJSON().content[0].attrs).toEqual({ id: "id-9", rule: showLocal });
    editor.commands.setContent('<div data-mka-audience data-id="z" data-rule="{not json"><p>q</p></div>');
    const attrs = editor.getJSON().content[0].attrs;
    expect(attrs.id).toBe("z");
    expect(attrs.rule).toEqual({ invalid: true });
    editor.destroy();
  });

  test("viewer-field and counterparts round trip", () => {
    const json = docJSON(
      { type: "paragraph", content: [{ type: "text", text: "In " }, { type: "mkaViewerField", attrs: { field: "majlis", fallback: "your Majlis" } }] },
      { type: "mkaCounterparts", attrs: { id: null } },
    );
    const editor = make(json);
    expect(editor.getJSON()).toEqual(json);
    expect(editor.getText()).toContain("your Majlis");
    editor.destroy();
  });
});

describe("hidden content is absent from the document DOM", () => {
  const json = docJSON(para("public"), section("a", "TOP-SECRET-TEXT"));

  test("before the controller has evaluated anything (initial state) a non-editable section holds no content", () => {
    const editor = make(json);
    const dom = editor.view.dom;
    expect(dom.textContent).toContain("public");
    expect(dom.textContent).not.toContain("TOP-SECRET-TEXT");
    expect(dom.querySelector("[data-mka-content]")).toBeNull();
    // the document itself still has it: only the DOM is gated
    expect(editor.state.doc.textContent).toContain("TOP-SECRET-TEXT");
    editor.destroy();
  });

  test("modes attach/detach the content element; hidden and loading never expose it", () => {
    const editor = make(json);
    const wrapper = editor.view.dom.querySelector("[data-mka-audience-section]");
    const view = audienceNodeViewFor(wrapper);
    expect(view).toBeTruthy();

    for (const mode of ["hidden", "loading", "placeholder"]) {
      view.setMode(mode);
      expect(editor.view.dom.textContent).not.toContain("TOP-SECRET-TEXT");
      expect(editor.view.dom.innerHTML).not.toContain("TOP-SECRET-TEXT");
    }
    view.setMode("hidden");
    expect(wrapper.style.display).toBe("none");
    view.setMode("loading");
    expect(wrapper.style.display).toBe("none");

    view.setMode("content");
    expect(editor.view.dom.textContent).toContain("TOP-SECRET-TEXT");
    expect(wrapper.style.display).toBe("");

    view.setMode("chrome", { collapsed: true });
    expect(editor.view.dom.textContent).not.toContain("TOP-SECRET-TEXT");
    view.setMode("chrome");
    expect(editor.view.dom.textContent).toContain("TOP-SECRET-TEXT");

    view.setMode("hidden");
    expect(editor.view.dom.textContent).not.toContain("TOP-SECRET-TEXT");
    editor.destroy();
  });

  test("hidden state survives a node update (typing elsewhere) without leaking", () => {
    const editor = make(json);
    editor.commands.insertContentAt(1, "x"); // edits the first paragraph; section re-checked by PM
    expect(editor.view.dom.textContent).not.toContain("TOP-SECRET-TEXT");
    editor.destroy();
  });

  test("authoring editors start with the content visible (an author never loses sight of their work)", () => {
    const editor = make(json, { editable: true });
    expect(editor.view.dom.textContent).toContain("TOP-SECRET-TEXT");
    editor.destroy();
  });
});

describe("invariants: unique ids and no nesting", () => {
  test("duplicate and missing ids in an authoring doc are repaired once the editor is created", async () => {
    const editor = make(docJSON(section("dup", "one"), section("dup", "two"), section(null, "three")), { editable: true });
    await tick(); // TipTap emits `create` asynchronously
    const found = ids(editor);
    expect(found.length).toBe(3);
    expect(new Set(found).size).toBe(3);
    expect(found.every(Boolean)).toBe(true);
    expect(found[0]).toBe("dup");
    editor.destroy();
  });

  test("paste of a copied section regenerates its id and keeps the rule", () => {
    const editor = make(docJSON(section("orig", "one"), para("")), { editable: true });
    const html = editor.getHTML();
    editor.commands.focus("end"); // cursor in the trailing paragraph, outside the section
    editor.view.pasteHTML(html);
    const found = ids(editor);
    expect(found.length).toBe(2);
    expect(new Set(found).size).toBe(2);
    editor.state.doc.descendants((n) => {
      if (n.type.name === "mkaAudience") expect(n.attrs.rule).toEqual(showLocal);
    });
    editor.destroy();
  });

  test("pasting a section INTO a section unwraps the pasted one (no nesting)", () => {
    const editor = make(docJSON(section("orig", "one")), { editable: true });
    const html = editor.getHTML();
    editor.commands.setTextSelection(2); // inside the section
    editor.view.pasteHTML(html);
    expect(ids(editor)).toEqual(["orig"]);
    expect(editor.state.doc.textContent.match(/one/g).length).toBe(2);
    editor.destroy();
  });

  test("nested sections are unwrapped, keeping the inner content", () => {
    const nested = { type: "mkaAudience", attrs: { id: "outer", rule: showLocal }, content: [para("outer-text"), section("inner", "inner-text")] };
    const editor = make(docJSON(nested), { editable: true });
    editor.commands.setContent(docJSON(nested)); // goes through appendTransaction
    expect(ids(editor)).toEqual(["outer"]);
    expect(editor.state.doc.textContent).toContain("inner-text");
    expect(editor.state.doc.textContent).toContain("outer-text");
    editor.destroy();
  });

  test("buildFixTransaction is a no-op on a clean document", () => {
    const editor = make(docJSON(section("a", "x"), section("b", "y")), { editable: true });
    expect(buildFixTransaction(editor.state)).toBeNull();
    editor.destroy();
  });
});

describe("commands", () => {
  const types = (editor) => editor.state.doc.content.content.map((n) => n.type.name);

  test("wrap a multi-block selection and open the picker for it", () => {
    const editor = make(docJSON(para("a"), para("b"), para("c")), { editable: true });
    editor.commands.setTextSelection({ from: 1, to: 5 });
    expect(editor.commands.setMkaAudience()).toBe(true);
    expect(types(editor)).toEqual(["mkaAudience", "paragraph"]);
    const [id] = ids(editor);
    expect(id).toBeTruthy();
    expect(editor.state.doc.child(0).childCount).toBe(2);
    expect(getAudienceStore(editor).get().openPickerFor).toBe(id);
    editor.destroy();
  });

  test("empty selection in a non-empty block inserts an empty section after it with the cursor inside", () => {
    const editor = make(docJSON(para("a"), para("b")), { editable: true });
    editor.commands.setTextSelection(2);
    expect(editor.commands.setMkaAudience()).toBe(true);
    expect(types(editor)).toEqual(["paragraph", "mkaAudience", "paragraph"]);
    expect(editor.state.doc.child(1).textContent).toBe("");
    const $from = editor.state.selection.$from;
    expect($from.node($from.depth - 1).type.name).toBe("mkaAudience");
    editor.destroy();
  });

  test("blank paragraph is wrapped in place", () => {
    const editor = make(docJSON(para("a"), para("")), { editable: true });
    editor.commands.setTextSelection(editor.state.doc.content.size - 1);
    expect(editor.commands.setMkaAudience()).toBe(true);
    expect(types(editor)).toEqual(["paragraph", "mkaAudience"]);
    editor.destroy();
  });

  test("no nesting: refused inside a section and when the selection contains one", () => {
    const editor = make(docJSON(section("a", "x"), para("y")), { editable: true });
    editor.commands.setTextSelection(3);
    expect(editor.commands.setMkaAudience()).toBe(false);
    editor.commands.selectAll();
    expect(editor.commands.setMkaAudience()).toBe(false);
    expect(ids(editor)).toEqual(["a"]);
    editor.destroy();
  });

  test("updateMkaAudienceRule and unsetMkaAudience", () => {
    const editor = make(docJSON(section("a", "x")), { editable: true });
    const rule = { v: 1, mode: "hide", groups: [{ level: ["regional"] }] };
    expect(editor.commands.updateMkaAudienceRule("a", rule)).toBe(true);
    expect(editor.getJSON().content[0].attrs.rule).toEqual(rule);
    expect(editor.commands.updateMkaAudienceRule("missing", rule)).toBe(false);
    expect(editor.commands.unsetMkaAudience("a")).toBe(true);
    expect(types(editor)).toEqual(["paragraph"]);
    expect(editor.state.doc.textContent).toBe("x");
    editor.destroy();
  });

  test("Mod-Alt-a is only active when authoring AND the feature flag is on", () => {
    const run = (editable, flag) => {
      const prev = process.env.NEXT_PUBLIC_MKA_AUDIENCE_ENABLED;
      process.env.NEXT_PUBLIC_MKA_AUDIENCE_ENABLED = flag;
      const editor = make(docJSON(para("a")), { editable });
      editor.commands.setTextSelection(1);
      const mac = /Mac|iP(hone|[oa]d)/.test(navigator.platform);
      const handled = editor.view.someProp("handleKeyDown", (f) => f(editor.view, new KeyboardEvent("keydown", { key: "a", code: "KeyA", altKey: true, metaKey: mac, ctrlKey: !mac })));
      const count = ids(editor).length;
      process.env.NEXT_PUBLIC_MKA_AUDIENCE_ENABLED = prev;
      editor.destroy();
      return { handled: !!handled, count };
    };
    expect(run(true, "1").count).toBe(1);
    expect(run(true, "0").count).toBe(0);
    expect(run(false, "1").count).toBe(0);
  });

  test("{{my_majlis}} and friends become a viewer-field chip", () => {
    const editor = make(docJSON(para("{{my_majlis}")), { editable: true });
    const end = editor.state.doc.content.size - 1;
    editor.commands.setTextSelection(end);
    editor.view.someProp("handleTextInput", (f) => f(editor.view, end, end, "}"));
    const para0 = editor.getJSON().content[0].content;
    expect(para0).toEqual([{ type: "mkaViewerField", attrs: { field: "majlis", fallback: "your Majlis" } }]);
    editor.destroy();

    const e2 = make(docJSON(para("{{my_role}")), { editable: true });
    const end2 = e2.state.doc.content.size - 1;
    e2.commands.setTextSelection(end2);
    e2.view.someProp("handleTextInput", (f) => f(e2.view, end2, end2, "}"));
    expect(e2.getJSON().content[0].content[0].attrs.field).toBe("role_title");
    e2.destroy();
  });
});
