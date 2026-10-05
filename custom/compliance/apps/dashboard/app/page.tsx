import { RagBadge } from "@/components/RagBadge";
import { AttentionList } from "@/components/AttentionList";
import { ChaseButton } from "@/components/ChaseButton";
import { FilterBar } from "@/components/FilterBar";
import { Heatmap } from "@/components/Heatmap";
import { PageHeader, Section, Shell } from "@/components/Shell";
import { Sparkline } from "@/components/Sparkline";
import { StatTiles } from "@/components/StatTiles";
import { EmptyState } from "@/components/StateViews";
import { TrendText } from "@/components/TrendText";
import { requireScoped } from "@/lib/access";
import { deptParam, regionLabel } from "@/lib/format";
import { overview, parseFilters } from "@/lib/queries";

export default async function Overview({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const data = await requireScoped();
  const f = parseFilters(await searchParams);
  const m = overview(data, f);
  const allDepts = [...new Map(data.rows.map((r) => [r.departmentSlug, r])).keys()].map((s) => ({ id: s || "executive", label: data.departments.find((d) => d.slug === s)?.name ?? "Executive (Qaids)" }));
  const allRegions = [...new Set(data.rows.map((r) => r.region))].sort().map((r) => ({ id: r || "_national", label: regionLabel(r) }));
  return (
    <Shell data={data}>
      <PageHeader title="Who needs attention" sub={<span className="flex flex-wrap items-center gap-2"><RagBadge rag={m.att.rag} /><span>{m.att.summary}</span></span>} actions={<ChaseButton filters={f} />} />
      <FilterBar show={["dept", "region"]} departments={allDepts} regions={allRegions} />
      {!m.rows.length ? <EmptyState title="No officeholders in this view" hint="Clear the filters, or ask for the roster to be loaded." /> : (
        <>
          <StatTiles agg={m.total} />
          <div className="flex flex-wrap items-center gap-4 text-sm"><Sparkline series={m.series} width={220} height={40} /><div><TrendText trend={m.trend} span="yesterday" /><br /><TrendText trend={m.trend7} span="last week" /></div></div>
          <Section title="Departments, worst first" hint="Ranked by how far behind the expected pace they are, then overdue and contact mistakes.">
            <AttentionList items={m.departments} hrefFor={(k) => `/department/${encodeURIComponent(deptParam(k))}`} limit={8} />
          </Section>
          <Section title="Department by region" hint="Each cell says its state in words. Select a cell to see who to chase.">
            <Heatmap model={m} />
          </Section>
        </>
      )}
    </Shell>
  );
}
