import { notFound } from "next/navigation";
import { aggregate, attention, chaseList } from "@mka/analytics/pure";
import { ChaseButton } from "@/components/ChaseButton";
import { FilterBar } from "@/components/FilterBar";
import { PeopleTable } from "@/components/PeopleTable";
import { RagBadge } from "@/components/RagBadge";
import { PageHeader, Section, Shell } from "@/components/Shell";
import { StatTiles } from "@/components/StatTiles";
import { requireScoped } from "@/lib/access";
import { STATUS_OPTIONS, safeDecode } from "@/lib/format";
import { CFG, applyFilters, parseFilters } from "@/lib/queries";

export default async function MajlisPage({ params, searchParams }: { params: Promise<{ majlis: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const data = await requireScoped();
  const majlis = safeDecode((await params).majlis);
  const f = { ...parseFilters(await searchParams), majlis };
  const all = data.rows.filter((r) => r.majlis === majlis);
  if (!all.length) notFound();
  const nameOf = (s: string) => data.departments.find((d) => d.slug === s)?.name ?? "Executive (Qaids)";
  const rows = applyFilters(all, { status: f.status, q: f.q });
  const agg = aggregate(majlis, rows, data.cycle);
  const att = attention(agg, data.cycle, data.asOf, CFG);
  const region = all[0]!.region;
  const people = chaseList(rows, (s) => s).concat(rows.filter((r) => r.stage === "attested"));
  return (
    <Shell data={data}>
      <PageHeader crumbs={[{ href: "/", label: "Overview" }, { href: `/region/${encodeURIComponent(region)}`, label: region }, { label: majlis }]} title={`Majlis ${majlis}`} sub={<span className="flex flex-wrap items-center gap-2"><RagBadge rag={att.rag} /><span>{att.summary}</span></span>} actions={<ChaseButton filters={f} />} />
      <StatTiles agg={agg} />
      <Section title="Officeholders">
        <FilterBar show={["status", "q"]} statuses={STATUS_OPTIONS} />
        <PeopleTable rows={people} asOf={data.asOf} deptName={nameOf} showDept caption={`${majlis} officeholders`} />
      </Section>
    </Shell>
  );
}
