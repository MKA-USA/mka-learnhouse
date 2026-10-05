export const CYCLES: Record<string, { startsOn: string; deadlineOn: string }> = {
  "2025-26": { startsOn: "2025-11-01", deadlineOn: "2025-12-01" },
  "2026-27": { startsOn: "2026-11-01", deadlineOn: "2026-12-01" },
};
export const DEFAULT_CYCLE = "2026-27";
export function cycleDef(label: string) {
  const c = CYCLES[label];
  if (!c) throw new Error(`unknown cycle ${label}; known: ${Object.keys(CYCLES).join(", ")}`);
  return { label, ...c };
}
