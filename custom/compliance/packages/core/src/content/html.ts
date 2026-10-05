import { parseDocument } from "htmlparser2";
import type { ChildNode, Element } from "domhandler";
import { marked } from "marked";
import { type PMDoc, type PMMark, type PMNode, p } from "./pm";

export interface ConvertResult { doc: PMDoc; imagesDropped: number; links: string[] }

const BLOCK = new Set(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "blockquote", "pre", "section", "article", "header", "footer", "hr"]);
const IGNORE = new Set(["style", "script", "head", "title", "meta", "link", "noscript"]);

function styleMarks(style: string | undefined): PMMark[] {
  if (!style) return [];
  const m: PMMark[] = [];
  const fw = /font-weight\s*:\s*([a-z0-9]+)/i.exec(style)?.[1];
  if (fw && (fw === "bold" || fw === "bolder" || Number(fw) >= 600)) m.push({ type: "bold" });
  if (/font-style\s*:\s*italic/i.test(style)) m.push({ type: "italic" });
  if (/text-decoration[^;]*underline/i.test(style)) m.push({ type: "underline" });
  return m;
}
const addMark = (marks: PMMark[], mk: PMMark) => (marks.some((x) => x.type === mk.type) ? marks : [...marks, mk]);

/** HTML -> ProseMirror. Strips all inline styling (keeps bold/italic/underline semantics), drops images/comments/style. */
export function htmlToProseMirror(html: string): ConvertResult {
  const root = parseDocument(html ?? "");
  let imagesDropped = 0;
  const links: string[] = [];

  function inline(nodes: ChildNode[], marks: PMMark[]): PMNode[] {
    const out: PMNode[] = [];
    for (const n of nodes) {
      if (n.type === "text") {
        const t = (n as unknown as { data: string }).data.replace(/[​ ]/g, " ").replace(/\s+/g, " ");
        if (t) out.push(marks.length ? { type: "text", text: t, marks } : { type: "text", text: t });
      } else if (n.type === "tag" || n.type === "script" || n.type === "style") {
        const el = n as Element; const name = el.name.toLowerCase();
        if (IGNORE.has(name)) continue;
        if (name === "br") { out.push({ type: "hardBreak" }); continue; }
        if (name === "img") { imagesDropped++; continue; }
        let mk = marks;
        for (const s of styleMarks(el.attribs?.style)) mk = addMark(mk, s);
        if (name === "strong" || name === "b") mk = addMark(mk, { type: "bold" });
        if (name === "em" || name === "i") mk = addMark(mk, { type: "italic" });
        if (name === "u") mk = addMark(mk, { type: "underline" });
        if (name === "a" && el.attribs?.href && /^(https?:|mailto:)/i.test(el.attribs.href.trim())) {
          const href = el.attribs.href.trim(); links.push(href);
          mk = addMark(mk, { type: "link", attrs: { href, target: "_blank", rel: "noopener noreferrer nofollow" } });
        }
        out.push(...inline(el.children as ChildNode[], mk));
      }
    }
    return out;
  }
  const trimInline = (arr: PMNode[]): PMNode[] => {
    const a = [...arr];
    while (a.length && a[0]!.type === "text" && !a[0]!.text!.trim()) a.shift();
    while (a.length && a[a.length - 1]!.type === "text" && !a[a.length - 1]!.text!.trim()) a.pop();
    if (a[0]?.type === "text") a[0] = { ...a[0], text: a[0].text!.replace(/^\s+/, "") };
    const l = a.length - 1;
    if (a[l]?.type === "text") a[l] = { ...a[l]!, text: a[l]!.text!.replace(/\s+$/, "") };
    // merge adjacent text nodes with identical marks
    const merged: PMNode[] = [];
    for (const n of a) {
      const prev = merged[merged.length - 1];
      if (prev && prev.type === "text" && n.type === "text" && JSON.stringify(prev.marks ?? []) === JSON.stringify(n.marks ?? [])) prev.text += n.text!;
      else merged.push({ ...n });
    }
    return merged;
  };

  /** Convert children as a sequence of blocks (inline runs become paragraphs). */
  function blocks(nodes: ChildNode[], marks: PMMark[]): PMNode[] {
    const out: PMNode[] = [];
    let run: ChildNode[] = [];
    const flush = () => {
      if (!run.length) return;
      const inl = trimInline(inline(run, marks));
      if (inl.length) out.push({ type: "paragraph", content: inl });
      run = [];
    };
    for (const n of nodes) {
      if (n.type === "tag") {
        const el = n as Element; const name = el.name.toLowerCase();
        if (IGNORE.has(name)) continue;
        if (BLOCK.has(name)) { flush(); out.push(...block(el, marks)); continue; }
      }
      run.push(n);
    }
    flush();
    return out;
  }

  function block(el: Element, marks: PMMark[]): PMNode[] {
    const name = el.name.toLowerCase();
    let mk = marks;
    for (const s of styleMarks(el.attribs?.style)) mk = addMark(mk, s);
    const kids = el.children as ChildNode[];
    switch (name) {
      case "p": case "pre": {
        // a <p> may contain block children (bad markup); handle generally
        const b = blocks(kids, mk);
        return b;
      }
      case "h1": case "h2": case "h3": case "h4": case "h5": case "h6": {
        const inl = trimInline(inline(kids, [])); // headings carry no extra marks
        return inl.length ? [{ type: "heading", attrs: { level: Number(name[1]) }, content: inl }] : [];
      }
      case "ul": case "ol": {
        const items = kids.filter((k) => k.type === "tag" && (k as Element).name.toLowerCase() === "li").map((k) => {
          const c = blocks((k as Element).children as ChildNode[], mk);
          return { type: "listItem", content: c.length ? c : [p()] } as PMNode;
        });
        if (!items.length) return [];
        return [name === "ul" ? { type: "bulletList", content: items } : { type: "orderedList", attrs: { start: 1 }, content: items }];
      }
      case "li": return blocks(kids, mk);
      case "blockquote": { const c = blocks(kids, mk); return c.length ? [{ type: "blockquote", content: c }] : []; }
      case "hr": return [];
      case "table": {
        const rows: Element[] = [];
        const collect = (ns: ChildNode[]) => { for (const n of ns) if (n.type === "tag") { const e = n as Element; const nm = e.name.toLowerCase(); if (nm === "tr") rows.push(e); else if (["thead", "tbody", "tfoot"].includes(nm)) collect(e.children as ChildNode[]); } };
        collect(kids);
        const prs: PMNode[] = rows.map((r) => ({
          type: "tableRow",
          content: (r.children as ChildNode[]).filter((c) => c.type === "tag" && ["td", "th"].includes((c as Element).name.toLowerCase())).map((c) => {
            const ce = c as Element; const cc = blocks(ce.children as ChildNode[], mk);
            const span = (v: string | undefined) => { const n = Number(v); return Number.isFinite(n) && n > 0 ? n : 1; };
            return { type: ce.name.toLowerCase() === "th" ? "tableHeader" : "tableCell", attrs: { colspan: span(ce.attribs?.colspan), rowspan: span(ce.attribs?.rowspan) }, content: cc.length ? cc : [p()] } as PMNode;
          }),
        })).filter((r) => r.content!.length);
        return prs.length ? [{ type: "table", content: prs }] : [];
      }
      case "thead": case "tbody": case "tfoot": case "tr": case "td": case "th": return blocks(kids, mk);
      default: return blocks(kids, mk); // div, section, ...
    }
  }

  const content = blocks(root.children as ChildNode[], []);
  return { doc: { type: "doc", content: content.length ? content : [p()] }, imagesDropped, links };
}

export function markdownToProseMirror(md: string): ConvertResult {
  return htmlToProseMirror(marked.parse(md ?? "", { async: false, gfm: true }) as string);
}
