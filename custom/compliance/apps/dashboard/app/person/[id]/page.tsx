import { Meter, Label } from "@heroui/react";
import { notFound } from "next/navigation";
import { PageHeader, Section, Shell } from "@/components/Shell";
import { StatusChip } from "@/components/StatusChip";
import { requireScoped } from "@/lib/access";
import { ago, deptParam, levelLabel, regionLabel, safeDecode, shortDate } from "@/lib/format";

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="grid grid-cols-[10rem_1fr] gap-2 py-2"><dt className="text-sm text-muted">{k}</dt><dd className="text-sm">{v}</dd></div>;
}

export default async function PersonPage({ params }: { params: Promise<{ id: string }> }) {
  const data = await requireScoped();
  const id = safeDecode((await params).id);
  const r = data.rows.find((x) => x.rosterId === id);
  if (!r) notFound();
  const dept = data.departments.find((d) => d.slug === r.departmentSlug)?.name ?? "Executive (Qaids)";
  const pctDone = r.lessonsTotal ? Math.round((r.lessonsDone / r.lessonsTotal) * 100) : 0;
  return (
    <Shell data={data}>
      <PageHeader crumbs={[{ href: "/", label: "Overview" }, { href: `/department/${encodeURIComponent(deptParam(r.departmentSlug))}`, label: dept }, { label: r.roleTitle }]} title={r.personName ?? r.roleTitle} sub={<StatusChip status={r.status} />} />
      <Section title="Role">
        <dl className="divide-y divide-border rounded-2xl border border-border bg-surface px-4">
          <Row k="Role" v={`${r.roleTitle} (${levelLabel(r.level)})`} />
          <Row k="Department" v={dept} />
          <Row k="Region / Majlis" v={`${regionLabel(r.region)}${r.majlis ? ` / ${r.majlis}` : ""}`} />
          <Row k="Mailbox" v={<a className="underline" href={`mailto:${r.email}`}>{r.email}</a>} />
          <Row k="Appointed" v={r.appointedOn ? shortDate(r.appointedOn) : "Start of cycle"} />
        </dl>
      </Section>
      <Section title="Progress">
        <dl className="divide-y divide-border rounded-2xl border border-border bg-surface px-4">
          <Row k="Lessons done" v={r.lessonsTotal ? (
            <Meter aria-label="Lessons done" value={pctDone} className="max-w-xs"><Label>{r.lessonsDone} of {r.lessonsTotal}</Label><Meter.Output /><Meter.Track><Meter.Fill /></Meter.Track></Meter>) : "Not enrolled yet"} />
          <Row k="Quiz average" v={r.quizAvg === null ? "No quiz taken" : `${r.quizAvg}%`} />
          <Row k="Sign-off" v={r.attestedAt ? `Signed off ${shortDate(r.attestedAt)}` : r.stage === "completed" ? "Lessons done, sign-off still to do" : "Not signed off"} />
          <Row k="Due" v={`${shortDate(r.dueOn)}${r.daysOverdue ? ` (${r.daysOverdue} days overdue)` : ""}`} />
          <Row k="Last activity" v={`${shortDate(r.lastActivityAt)} (${ago(r.lastActivityAt, data.asOf)})`} />
          <Row k="Contact check" v={!r.selfCheckAnswered ? "Not answered" : r.selfCheckMismatches ? `${r.selfCheckMismatches} answer(s) differ from the roster` : "Matches the roster"} />
        </dl>
      </Section>
    </Shell>
  );
}
