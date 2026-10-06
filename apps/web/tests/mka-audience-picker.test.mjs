import { describe, expect, test } from "bun:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PickerBody } from "../components/mka/editor/AudiencePicker.tsx";
import { AUDIENCE_KEYWORDS } from "../components/mka/editor/fields.ts";
import { mockOptions } from "../services/mka/attributes.mock.ts";

const props = (over = {}) => ({
  value: { v: 1, mode: "show", groups: [{}] },
  onChange() {}, onDone() {}, onCancel() {},
  options: mockOptions(), authorDepartment: null, count: { state: "idle" }, isNew: false,
  ...over,
});
const footer = (html) => html.match(/<div data-testid="audience-picker-footer" class="([^"]*)"/)?.[1] ?? "";

describe("F3: phone sheet footer", () => {
  test("in the sheet the Cancel/Done footer is sticky and clears the safe area", () => {
    const cls = footer(renderToStaticMarkup(React.createElement(PickerBody, props({ inSheet: true }))));
    expect(cls).toContain("sticky");
    expect(cls).toContain("bottom-0");
    expect(cls).toContain("safe-area-inset-bottom");
  });
  test("in the desktop popover it is an ordinary footer", () => {
    expect(footer(renderToStaticMarkup(React.createElement(PickerBody, props())))).not.toContain("sticky");
  });
});

describe("F4: Hide-from with no filters", () => {
  test("the picker says only non-officeholders will see it", () => {
    const html = renderToStaticMarkup(React.createElement(PickerBody, props({ value: { v: 1, mode: "hide", groups: [{}] } })));
    expect(html).toContain("Only people who aren&#x27;t officeholders will see this.");
  });
  test("no warning for an ordinary hide rule or a show rule", () => {
    for (const value of [{ v: 1, mode: "hide", groups: [{ level: ["local"] }] }, { v: 1, mode: "show", groups: [{}] }]) {
      expect(renderToStaticMarkup(React.createElement(PickerBody, props({ value })))).not.toContain("aren&#x27;t officeholders");
    }
  });
});

describe("slash discoverability", () => {
  test("the Audience section item matches how authors describe it", () => {
    for (const w of ["who", "see", "visible", "show", "hide", "only", "restrict", "target", "who can see", "role", "roles", "officeholder"]) {
      expect(AUDIENCE_KEYWORDS).toContain(w);
    }
  });
});
