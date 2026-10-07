import { describe, expect, test } from "bun:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MkaProfileFields from "../components/mka/MkaProfileFields.tsx";

const OPTIONS = {
  majlis: [{ name: "Zion", region: "Midwest" }],
  tanzeem: [
    { value: "khuddam", label: "Khuddam" },
    { value: "ansar", label: "Ansarullah" },
    { value: "lajna", label: "Lajna Imaillah" },
  ],
};

const render = (values = {}, extra = {}) => {
  const qc = new QueryClient();
  qc.setQueryData(["mka-profile-options"], OPTIONS);
  return renderToStaticMarkup(
    React.createElement(
      QueryClientProvider,
      { client: qc },
      React.createElement(MkaProfileFields, {
        values: { majlis: "", mobile: "", amc_id: "", tanzeem: "", ...values },
        onChange() {},
        idPrefix: "t",
        ...extra,
      }),
    ),
  );
};

describe("Tanzeem radio group", () => {
  test("renders a radiogroup with one radio per option plus Not specified", () => {
    const html = render();
    expect(html).toContain('role="radiogroup"');
    expect(html.match(/role="radio"/g)?.length).toBe(4);
    for (const l of ["Not specified", "Khuddam", "Ansarullah", "Lajna Imaillah"]) {
      expect(html).toContain(l);
    }
    expect(html).not.toContain('id="t-tanzeem" role="combobox"');
  });

  test("empty value checks Not specified; a set value checks that option", () => {
    const empty = render();
    expect(empty).toMatch(/value="__none__"[^>]*aria-checked="true"|aria-checked="true"[^>]*value="__none__"/);
    const set = render({ tanzeem: "ansar" });
    expect(set).toMatch(/aria-checked="true"[^>]*value="ansar"|value="ansar"[^>]*aria-checked="true"/);
  });

  test("stacks on narrow screens and goes horizontal from sm", () => {
    const html = render();
    expect(html).toContain("flex-col");
    expect(html).toContain("sm:flex-row");
  });

  test("labelled, optional, and error wired via aria-describedby", () => {
    const html = render({}, { errors: { tanzeem: "Bad" } });
    expect(html).toContain("Tanzeem (optional)");
    expect(html).toContain('aria-labelledby="t-tanzeem-label"');
    expect(html).toContain('aria-describedby="t-tanzeem-error"');
    expect(html).toContain('id="t-tanzeem-error"');
  });

  test("disabled propagates to radios", () => {
    expect(render({}, { disabled: true })).toContain('data-disabled=""');
  });
});
