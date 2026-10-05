import type { Rag } from "@mka/analytics/pure";
import { RAG_META } from "@/lib/format";

/** Word + glyph + colour, so it is readable without colour vision. */
export function RagBadge({ rag, className = "" }: { rag: Rag; className?: string }) {
  const m = RAG_META[rag];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${m.cell} ${m.text} ${className}`}>
      <span aria-hidden="true">{m.glyph}</span>
      <span>{m.word}</span>
    </span>
  );
}
