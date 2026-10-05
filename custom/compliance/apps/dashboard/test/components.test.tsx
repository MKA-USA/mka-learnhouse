import "./setup";
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { buildFixtureDataset } from "@mka/analytics/pure";
import { AttentionList } from "@/components/AttentionList";
import { Heatmap } from "@/components/Heatmap";
import { PeopleTable } from "@/components/PeopleTable";
import { RagBadge } from "@/components/RagBadge";
import { Sparkline } from "@/components/Sparkline";
import { StatTiles } from "@/components/StatTiles";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { StatusChip } from "@/components/StatusChip";
import { scopeDataset } from "@/lib/access";
import { overview } from "@/lib/queries";

const ds = buildFixtureDataset({ historyDays: 8 });
const data = scopeDataset(ds, { email: "m@x.invalid", name: null }, { status: "matched", is_officeholder: true, level: "national", department: null, role: "motamid", majlis: null, region: null }, [], false);
const m = overview(data, {});

describe("component smoke", () => {
  test("RAG is never colour alone: every state renders a word and a glyph", () => {
    for (const [rag, word] of [["red", "Act now"], ["amber", "Watch"], ["green", "On track"], ["none", "No data"]] as const) {
      const html = renderToStaticMarkup(<RagBadge rag={rag} />);
      expect(html).toContain(word); expect(html).toContain('aria-hidden="true"');
    }
  });
  test("heatmap: accessible table, every cell a link with words", () => {
    const html = renderToStaticMarkup(<Heatmap model={m} />);
    expect(html).toContain("<caption"); expect(html).toContain('scope="row"'); expect(html).toContain('scope="col"');
    expect(html).toMatch(/aria-label="Tarbiyyat, [^"]+: (Act now|Watch|On track)\./);
  });
  test("attention list shows reasons, sparkline has a text alternative", () => {
    const html = renderToStaticMarkup(<AttentionList items={m.departments} hrefFor={(k) => `/department/${k}`} limit={3} />);
    expect(html).toContain("haven&#x27;t started"); expect(html).toContain('role="img"'); expect(html).toContain("<ol");
  });
  test("sparkline with too little history degrades to text", () => {
    expect(renderToStaticMarkup(<Sparkline series={[]} />)).toContain("no trend yet");
  });
  test("stat tiles, status chips, states", () => {
    expect(renderToStaticMarkup(<StatTiles agg={m.total} />)).toContain("Officeholders");
    for (const s of ["not_started", "in_progress", "completed", "attested", "overdue"] as const) expect(renderToStaticMarkup(<StatusChip status={s} />).length).toBeGreaterThan(20);
    expect(renderToStaticMarkup(<EmptyState title="Nothing" hint="h" />)).toContain('role="status"');
    expect(renderToStaticMarkup(<ErrorState detail="d" />)).toContain("role");
    expect(renderToStaticMarkup(<LoadingState />)).toContain('aria-busy="true"');
  });
  test("people table renders rows and an empty state", () => {
    const rows = data.rows.filter((r) => r.departmentSlug === "tarbiyyat").slice(0, 5);
    const html = renderToStaticMarkup(<PeopleTable rows={rows} asOf={data.asOf} deptName={() => "Tarbiyyat"} caption="People" />);
    expect(html).toContain(rows[0]!.email);
    expect(renderToStaticMarkup(<PeopleTable rows={[]} asOf={data.asOf} deptName={() => ""} caption="x" />)).toContain("Nobody matches");
  });
});
