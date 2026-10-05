import { notFound } from "next/navigation";
import { aggregate, attention, chaseList } from "@mka/analytics/pure";
import { AttentionList } from "@/components/AttentionList";
import { ChaseButton } from "@/components/ChaseButton";
import { FilterBar } from "@/components/FilterBar";
import { PeopleTable } from "@/components/PeopleTable";
import { RagBadge } from "@/components/RagBadge";
import { PageHeader, Section, Shell } from "@/components/Shell";
import { StatTiles } from "@/components/StatTiles";
import { requireScoped } from "@/lib/access";
import { STATUS_OPTIONS, deptParam, regionLabel, safeDecode } from "@/lib/format";
import { CFG, applyFilters, groupRows, parseFilters } from "@/lib/queries";

export default async function RegionPage({ params, searchParams }: { params: Promise<{ region: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const data = await requireScoped();
  const raw = safeDecode((await params).region);
  const region = raw === "_national" ? "" : raw;
  const f = { ...parseFilters(await searchParams), region };
  const regionRows = data.rows.filter((r) => r.region === region);
  if (!regionRows.length) notFound();
  const nameOf = (s: string) => data.departments.find((d) => d.slug === s)?.name ?? "Executive (Qaids)";
  const rows = applyFilters(regionRows, { dept: f.dept, status: f.status, q: f.q });
  const agg = aggregate(region, rows, data.cycle);
  const att = attention(agg, data.cycle, data.asOf, CFG);
  const depts = [...new Set(regionRows.map((r) => r.departmentSlug))].map((s) => ({ id: deptParam(s), label: nameOf(s) }));
  const people = chaseList(rows, (s) => s).concat(rows.filter((r) => r.stage === "attested"));
  return (
    <Shell data={data}>
      <PageHeader crumbs={[{ href: "/", label: "Overview" }, { label: `Region: ${regionLabel(region)}` }]} title={`${regionLabel(region)} region`} sub={<span className="flex flex-wrap items-center gap-2"><RagBadge rag={att.rag} /><span>{att.summary}</span></span>} actions={<ChaseButton filters={f} />} />
      <StatTiles agg={agg} />
      <Section title="By department"><AttentionList items={groupRows(data, regionRows, "department", nameOf)} hrefFor={(k) => `/department/${encodeURIComponent(deptParam(k))}`} /></Section>
      <Section title="Majalis"><AttentionList items={groupRows(data, regionRows.filter((r) => r.majlis), "majlis", (k) => k)} hrefFor={(k) => `/majlis/${encodeURIComponent(k)}`} /></Section>
      <Section title="People">
        <FilterBar show={["dept", "status", "q"]} departments={depts} statuses={STATUS_OPTIONS} />
        <PeopleTable rows={people} asOf={data.asOf} deptName={nameOf} showDept caption={`${regionLabel(region)} officeholders`} />
      </Section>
    </Shell>
  );
}
