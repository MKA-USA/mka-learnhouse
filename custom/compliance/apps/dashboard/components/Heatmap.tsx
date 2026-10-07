import Link from "next/link";
import { RAG_META, deptParam, pct, regionLabel, regionParam } from "@/lib/format";
import type { overview } from "@/lib/queries";

type Model = ReturnType<typeof overview>;

/** Department x region grid. Each cell is a link (keyboard reachable) and says its state in words. */
export function Heatmap({ model }: { model: Model }) {
  const { departments, regions, heat } = model;
  if (!departments.length) return null;
  return (
    <div className="max-h-[60vh] overflow-auto rounded-2xl border border-border bg-surface">
      <table className="w-full min-w-[720px] border-collapse text-sm">
        <caption className="sr-only">Signed-off share by department and region. Each cell shows the state in words, the signed-off percentage and the number of officeholders.</caption>
        <thead className="sticky top-0 z-10 bg-surface">
          <tr>
            <th scope="col" className="sticky left-0 z-20 bg-surface p-2 text-left font-medium">Department</th>
            {regions.map((r) => <th key={r} scope="col" className="bg-surface p-2 text-left text-xs font-medium text-muted">{regionLabel(r)}</th>)}
          </tr>
        </thead>
        <tbody>
          {departments.map((d) => (
            <tr key={d.key} className="border-t border-border">
              <th scope="row" className="sticky left-0 bg-surface p-2 text-left font-medium"><Link className="hover:underline" href={`/department/${encodeURIComponent(deptParam(d.key))}`}>{d.label}</Link></th>
              {regions.map((r) => {
                const c = heat(d.key, r);
                if (!c) return <td key={r} className="p-1"><span className="block rounded-lg p-2 text-center text-xs text-muted" aria-label="No officeholders">·</span></td>;
                const m = RAG_META[c.att.rag];
                const label = `${d.label}, ${regionLabel(r)}: ${m.word}. ${pct(c.agg.attestedPct)} signed off of ${c.agg.expected}. ${c.att.summary}`;
                return (
                  <td key={r} className="p-1">
                    <Link aria-label={label} title={label} href={`/department/${encodeURIComponent(deptParam(d.key))}?region=${encodeURIComponent(regionParam(r))}`} className={`block rounded-lg border p-1.5 text-center leading-tight hover:brightness-95 ${m.cell}`}>
                      <span className={`block text-xs font-semibold ${m.text}`}><span aria-hidden="true">{m.glyph} </span>{m.word}</span>
                      <span className="block text-[11px] tabular-nums text-muted">{pct(c.agg.attestedPct)} of {c.agg.expected}</span>
                    </Link>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
