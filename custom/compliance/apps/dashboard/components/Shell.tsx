import { Chip } from "@heroui/react";
import Link from "next/link";
import { signOut } from "@/auth";
import { PersonaSwitcher } from "@/components/PersonaSwitcher";
import { diffDays } from "@mka/analytics/pure";
import type { ScopedData } from "@/lib/access";
import { shortDate } from "@/lib/format";

export function Shell({ data, children }: { data: ScopedData; children: React.ReactNode }) {
  const day = Math.max(0, diffDays(data.asOf, data.cycle.startsOn));
  const left = diffDays(data.cycle.deadlineOn, data.asOf);
  return (
    <>
      <a href="#main" className="skip-link">Skip to content</a>
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
          <Link href="/" className="text-base font-semibold">MKA compliance</Link>
          <nav aria-label="Primary" className="text-sm text-muted"><Link className="hover:underline" href="/">Overview</Link></nav>
          <span className="ml-auto flex flex-wrap items-center gap-3 text-sm">
            <Chip size="sm"><Chip.Label>Viewing: {data.scopeText}</Chip.Label></Chip>
            {data.viewer.devPersona ? (
              <span className="flex items-center gap-2">
                <span className="rounded bg-warning-soft px-1.5 py-0.5 text-xs font-medium text-warning">Dev mode</span>
                <PersonaSwitcher current={data.viewer.devPersona} />
                <form action={async () => { "use server"; await signOut({ redirectTo: "/login" }); }}><button className="underline" type="submit">Sign out</button></form>
              </span>
            ) : (
              <form action={async () => { "use server"; await signOut({ redirectTo: "/login" }); }}><button className="underline" type="submit">Sign out</button></form>
            )}
          </span>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-6xl space-y-6 px-4 py-6">
        <p className="text-sm text-muted">
          Cycle {data.cycle.label} · data as of {shortDate(data.asOf)} · day {day} of {diffDays(data.cycle.deadlineOn, data.cycle.startsOn)} · {left >= 0 ? `${left} days to the ${shortDate(data.cycle.deadlineOn)} deadline` : `${-left} days past the deadline`}
          {data.source === "fixtures" ? <strong className="ml-2 rounded bg-warning-soft px-1.5 py-0.5 text-warning">Demo data (synthetic)</strong> : null}
        </p>
        {children}
      </main>
    </>
  );
}

export function PageHeader({ title, sub, actions, crumbs }: { title: string; sub?: React.ReactNode; actions?: React.ReactNode; crumbs?: { href?: string; label: string }[] }) {
  return (
    <div className="space-y-1">
      {crumbs?.length ? (
        <nav aria-label="Breadcrumb" className="text-sm text-muted">
          <ol className="flex items-center gap-1.5">
            {crumbs.map((c, i) => (
              <li key={c.label} className="flex items-center gap-1.5">
                {i > 0 ? <span aria-hidden="true" className="text-muted/60">/</span> : null}
                {c.href ? <Link className="hover:underline" href={c.href}>{c.label}</Link> : <span aria-current="page">{c.label}</span>}
              </li>
            ))}
          </ol>
        </nav>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {actions}
      </div>
      {sub ? <div className="text-sm">{sub}</div> : null}
    </div>
  );
}

export function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="space-y-3">
      <div><h2 className="text-lg font-semibold">{title}</h2>{hint ? <p className="text-sm text-muted">{hint}</p> : null}</div>
      {children}
    </section>
  );
}
