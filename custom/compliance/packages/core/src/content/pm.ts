/** Minimal ProseMirror JSON builders matching the LearnHouse (TipTap) editor schema. */
export type PMMark = { type: string; attrs?: Record<string, unknown> };
export type PMNode = { type: string; attrs?: Record<string, unknown>; content?: PMNode[]; text?: string; marks?: PMMark[] };
export type PMDoc = { type: "doc"; content: PMNode[] };

export const doc = (...content: PMNode[]): PMDoc => ({ type: "doc", content });
export const text = (t: string, marks?: PMMark[]): PMNode => (marks?.length ? { type: "text", text: t, marks } : { type: "text", text: t });
const inl = (c: string | PMNode[]): PMNode[] => (typeof c === "string" ? (c ? [text(c)] : []) : c);
export const p = (c: string | PMNode[] = ""): PMNode => { const i = inl(c); return i.length ? { type: "paragraph", content: i } : { type: "paragraph" }; };
export const h = (level: number, c: string | PMNode[]): PMNode => ({ type: "heading", attrs: { level }, content: inl(c) });
export const li = (c: string | PMNode[] | PMNode): PMNode => ({ type: "listItem", content: typeof c === "object" && !Array.isArray(c) ? [c] : [p(c)] });
export const ul = (items: (string | PMNode[] | PMNode)[]): PMNode => ({ type: "bulletList", content: items.map(li) });
export const ol = (items: (string | PMNode[] | PMNode)[]): PMNode => ({ type: "orderedList", attrs: { start: 1 }, content: items.map(li) });
export const bold = (t: string): PMNode => text(t, [{ type: "bold" }]);
export const link = (t: string, href: string): PMNode => text(t, [{ type: "link", attrs: { href, target: "_blank", rel: "noopener noreferrer nofollow" } }]);
export const calloutInfo = (c: string | PMNode[]): PMNode => ({ type: "calloutInfo", content: inl(c) });
export const calloutWarning = (c: string | PMNode[]): PMNode => ({ type: "calloutWarning", content: inl(c) });
export const table = (header: string[], rows: string[][]): PMNode => ({
  type: "table",
  content: [
    { type: "tableRow", content: header.map((x) => ({ type: "tableHeader", attrs: { colspan: 1, rowspan: 1 }, content: [p(x)] })) },
    ...rows.map((r) => ({ type: "tableRow", content: r.map((x) => ({ type: "tableCell", attrs: { colspan: 1, rowspan: 1 }, content: [p(x)] })) })),
  ],
});
export const blockEmbed = (embedUrl: string): PMNode => ({ type: "blockEmbed", attrs: { embedUrl, embedType: "url", embedHeight: 400, embedWidth: "100%", alignment: "center" } });

/** Plain text of a node tree (for hashing, quiz building, flags). */
export function plainText(n: PMNode | PMDoc | undefined): string {
  if (!n) return "";
  if (n.type === "text") return (n as PMNode).text ?? "";
  const kids = (n.content ?? []).map(plainText);
  const sep = ["doc", "bulletList", "orderedList", "table", "tableRow"].includes(n.type) || n.type === "listItem" ? "\n" : n.type === "tableCell" || n.type === "tableHeader" ? " | " : "";
  return kids.join(sep) + (["paragraph", "heading"].includes(n.type) ? "\n" : "");
}
