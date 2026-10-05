import { notFound } from "next/navigation";
import { chaseList } from "@mka/analytics/pure";
import { AttentionList } from "@/components/AttentionList";
import { ChaseButton } from "@/components/ChaseButton";
import { FilterBar } from "@/components/FilterBar";
import { PeopleTable } from "@/components/PeopleTable";
import { RagBadge } from "@/components/RagBadge";
import { PageHeader, Section, Shell } from "@/components/Shell";
import { StatTiles } from "@/components/StatTiles";
import { requireScoped } from "@/lib/access";
import { STATUS_OPTIONS, deptFromParam, regionLabel, regionParam, safeDecode } from "@/lib/format";
import { CFG, applyFilters, groupRows, parseFilters } from "@/lib/queries";
import { aggregate, attention } from "@mka/analytics/pure";

export default async function DepartmentPage({ params, searchParams }: { params: Promise<{ slug: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const data = await requireScoped();
  const slug = deptFromParam(safeDecode((await params).slug));
  const f = { ...parseFilters(await searchParams), dept: slug };
  const deptRows = data.rows.filter((r) => r.departmentSlug === slug);
  if (!deptRows.length) notFound();                               // out of scope looks identical to "does not exist"
  const name = data.departments.find((d) => d.slug === slug)?.name ?? "Executive (Qaids)";
  const rows = applyFilters(deptRows, { region: f.region, status: f.status, q: f.q });
  const agg = aggregate(slug, rows, data.cycle);
  const att = attention(agg, data.cycle, data.asOf, CFG);
  const byRegion = groupRows(data, deptRows, "region", regionLabel);
  const byMajlis = groupRows(data, rows.filter((r) => r.majlis), "majlis", (k) => k);
  const regions = [...new Set(deptRows.map((r) => r.region))].sort().map((r) => ({ id: regionParam(r), label: regionLabel(r) }));
  const people = chaseList(rows, (s) => s).concat(rows.filter((r) => r.stage === "attested"));
  return (
    <Shell data={data}>
      <PageHeader crumbs={[{ href: "/", label: "Overview" }, { label: name }]} title={name} sub={<span className="flex flex-wrap items-center gap-2"><RagBadge rag={att.rag} /><span>{att.summary}</span></span>} actions={<ChaseButton filters={f} />} />
      <StatTiles agg={agg} />
      <Section title="By region" hint="Where this department is behind."><AttentionList items={byRegion} hrefFor={(k) => `/department/${encodeURIComponent(slug || "executive")}?region=${encodeURIComponent(regionParam(k))}`} /></Section>
      {byMajlis.length ? <Section title="Majalis to chase" hint="Worst first."><AttentionList items={byMajlis} limit={10} hrefFor={(k) => `/majlis/${encodeURIComponent(k)}`} /></Section> : null}
      <Section title="People">
        <FilterBar show={["region", "status", "q"]} regions={regions} statuses={STATUS_OPTIONS} />
        <PeopleTable rows={people} asOf={data.asOf} deptName={() => name} caption={`${name} officeholders`} />
      </Section>
    </Shell>
  );
}
