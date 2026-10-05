/** Small RFC-4180 parser: BOM, CRLF, quoted fields with commas/newlines/escaped quotes. Never throws. */
export interface CsvRow { line: number; cells: string[] }
export function parseCsv(input: string): { headers: string[]; rows: CsvRow[] } {
  const s = input.replace(/^﻿/, "");
  const records: CsvRow[] = [];
  let cur: string[] = []; let field = ""; let inQ = false; let line = 1; let startLine = 1; let any = false;
  const endField = () => { cur.push(field); field = ""; };
  const endRecord = () => { endField(); if (cur.length > 1 || cur[0]!.trim() !== "") records.push({ line: startLine, cells: cur }); cur = []; any = false; };
  for (let i = 0; i < s.length; i++) {
    const c = s[i]!;
    if (inQ) {
      if (c === '"') { if (s[i + 1] === '"') { field += '"'; i++; } else inQ = false; }
      else { field += c; if (c === "\n") line++; }
    } else if (c === '"' && field === "") { inQ = true; any = true; }
    else if (c === ",") { endField(); any = true; }
    else if (c === "\r") { /* skip */ }
    else if (c === "\n") { endRecord(); line++; startLine = line; }
    else { field += c; any = true; }
  }
  if (any || field !== "" || cur.length) endRecord();
  const header = records.shift();
  const headers = (header?.cells ?? []).map((h) => h.trim().toLowerCase().replace(/\s+/g, "_"));
  return { headers, rows: records };
}
