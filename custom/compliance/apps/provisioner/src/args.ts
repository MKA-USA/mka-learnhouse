/** Tiny argv parser: positional + --flag [value]. */
export function parseArgs(argv: string[]) {
  const pos: string[] = []; const flags = new Map<string, string | true>();
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith("--")) {
      const [k, v] = a.slice(2).split("=");
      if (v !== undefined) flags.set(k!, v);
      else if (argv[i + 1] && !argv[i + 1]!.startsWith("--")) flags.set(k!, argv[++i]!);
      else flags.set(k!, true);
    } else pos.push(a);
  }
  return { pos, flag: (k: string) => flags.get(k), str: (k: string, d?: string) => { const v = flags.get(k); return typeof v === "string" ? v : d; }, has: (k: string) => flags.has(k) };
}
export type Args = ReturnType<typeof parseArgs>;
