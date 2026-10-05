import { describe, expect, test } from "bun:test";
import { htmlToProseMirror, markdownToProseMirror } from "../src/content/html";
import { plainText } from "../src/content/pm";

describe("htmlToProseMirror", () => {
  test("strips Google-Docs inline styling but keeps bold from font-weight", () => {
    const r = htmlToProseMirror(`<p dir="ltr" style="margin:0;line-height:1.2"><span style="font-size:12pt;font-family:'Maven Pro';font-weight:700;color:#000">Objective 1</span><span style="font-weight:400"> text</span></p>`);
    expect(JSON.stringify(r.doc)).not.toContain("font-size");
    expect(r.doc.content[0]).toEqual({ type: "paragraph", content: [
      { type: "text", text: "Objective 1", marks: [{ type: "bold" }] }, { type: "text", text: " text" }] });
  });
  test("tables with colspan, ignores comments/style junk", () => {
    const r = htmlToProseMirror(`<!--td {border: 1px solid #ccc;}br {mso-data-placement:same-cell;}--><style>td{x:y}</style><table><tbody><tr><td colspan="3"><p>A</p></td></tr><tr><td>1</td><td>2</td><td></td></tr></tbody></table>`);
    expect(r.doc.content.length).toBe(1);
    const t = r.doc.content[0]!;
    expect(t.type).toBe("table");
    expect(t.content![0]!.content![0]!.attrs).toEqual({ colspan: 3, rowspan: 1 });
    expect(plainText(r.doc)).not.toContain("border");
  });
  test("lists, links, headings, br, images dropped", () => {
    const r = htmlToProseMirror(`<h2 style="x:y">Title</h2><ul><li>One</li><li><a href="https://alislam.org/x">Two</a></li></ul>line<br>two<img src="a.png">`);
    expect(r.imagesDropped).toBe(1);
    expect(r.links).toEqual(["https://alislam.org/x"]);
    expect(r.doc.content[0]).toEqual({ type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "Title" }] });
    expect(r.doc.content[1]!.type).toBe("bulletList");
    expect(JSON.stringify(r.doc.content[1])).toContain('"type":"link"');
    expect(r.doc.content[2]!.content!.map((n) => n.type)).toEqual(["text", "hardBreak", "text"]);
  });
  test("empty input yields a valid doc", () => { expect(htmlToProseMirror("").doc.content.length).toBe(1); });
  test("markdown path", () => {
    const r = markdownToProseMirror("# H\n\n- a\n- b\n\n**x** y");
    expect(r.doc.content.map((n) => n.type)).toEqual(["heading", "bulletList", "paragraph"]);
  });
});
