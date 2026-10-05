export type Severity = "error" | "warn" | "info";
export interface Issue { file: string; line: number; severity: Severity; code: string; message: string }
export const SHEET_ERROR_RE = /^#(REF|N\/A|VALUE|NAME\?|NAME|DIV\/0|NULL|NUM)[!?]?$/i;
