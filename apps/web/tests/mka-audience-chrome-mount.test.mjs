import { describe, expect, test } from "bun:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const { Editor } = await import("@tiptap/core");
const { default: StarterKit } = await import("@tiptap/starter-kit");
const { mkaEditorExtensions } = await import("../components/mka/editor/index.ts");
const { ReadOnlyBadge } = await import("../components/mka/editor/AudienceHeader.tsx");

const para = (t) => ({ type: "paragraph", content: [{ type: "text", text: t }] });
const section = { type: "mkaAudience", attrs: { id: "a", rule: { v: 1, mode: "show", groups: [{ level: ["local"] }] } }, content: [para("x")] };
const make = () =>
  new Editor({ extensions: [StarterKit.configure({ trailingNode: false }), ...mkaEditorExtensions({ editable: false })], content: { type: "doc", content: [para("p"), section] } });

describe("ensureChrome: created at the right time, not at plugin-view time", () => {
  test("no content component yet (editor just created): nothing is mounted, nothing is lost", () => {
    const e = make();
    expect(e.storage.mkaAudience.chromeRenderer).toBeNull();
    e.destroy();
  });

  test("once EditorContent has created its content component, rebuilding node views mounts the chrome", () => {
    const e = make();
    const registered = [];
    e.contentComponent = { setRenderer: (id) => registered.push(id), removeRenderer() {} };
    e.createNodeViews(); // what EditorContent.init() does right after creating contentComponent
    expect(e.storage.mkaAudience.chromeRenderer).toBeTruthy();
    expect(e.view.dom.parentElement.querySelector(".mka-audience-chrome")).not.toBeNull();
    // idempotent: another node-view rebuild does not mount a second one
    const first = e.storage.mkaAudience.chromeRenderer;
    e.createNodeViews();
    expect(e.storage.mkaAudience.chromeRenderer).toBe(first);
    e.destroy();
  });

  test("a NEW content component (remount) replaces the stale renderer", () => {
    const e = make();
    e.contentComponent = { setRenderer() {}, removeRenderer() {} };
    e.createNodeViews();
    const first = e.storage.mkaAudience.chromeRenderer;
    e.contentComponent = { setRenderer() {}, removeRenderer() {} };
    e.createNodeViews();
    expect(e.storage.mkaAudience.chromeRenderer).not.toBe(first);
    expect(e.view.dom.parentElement.querySelectorAll(".mka-audience-chrome").length).toBe(1);
    e.destroy();
  });
});

describe("FINDING-4: read-only badge reads like the author header", () => {
  test("a hide rule says Hidden from: National officeholders (not Everyone except ...)", () => {
    const html = renderToStaticMarkup(React.createElement(ReadOnlyBadge, { rule: { v: 1, mode: "hide", groups: [{ level: ["national"] }] }, label: "Everyone except national officeholders" }));
    const visible = html.replace(/<[^>]*>/g, "").replace(/&[^;]+;/g, " ");
    expect(visible).toContain("Hidden from");
    expect(visible).toContain("National officeholders");
    expect(visible).not.toContain("Everyone except");
  });
  test("a show rule is unchanged", () => {
    const html = renderToStaticMarkup(React.createElement(ReadOnlyBadge, { rule: { v: 1, mode: "show", groups: [{ level: ["local"] }] }, label: "Local officeholders" }));
    expect(html).toContain("Visible to");
    expect(html).toContain("Local officeholders");
  });
});
