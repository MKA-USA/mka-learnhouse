#!/usr/bin/env -S npx tsx
import { readFileSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { checkText, parseEditions, DEFAULT_THRESHOLDS, type CandidateResult } from './index.js';

const USAGE = `Usage: quran-check [options] "text..."
       quran-check --file path.txt
       echo "text" | quran-check

Options:
  --file <path>        read text from a file
  --editions <csv>     editions to fetch (default en). Known: en,zk,ur,sc,v5,sp_en,sp_ur
  --accept <n>         cite probability >= n => confirmed (default ${DEFAULT_THRESHOLDS.accept}, untuned)
  --reject <n>         cite probability <= n => rejected (default ${DEFAULT_THRESHOLDS.reject}, untuned)
  --json               machine-readable output
  -h, --help
Requires TYPESAFE_API_KEY (Jev) when the text contains any parseable reference.`;

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const c of process.stdin) chunks.push(c as Buffer);
  return Buffer.concat(chunks).toString('utf8');
}

const pct = (n: number) => `${(n * 100).toFixed(0)}%`;

function render(r: CandidateResult): string {
  const c = r.candidate;
  const ref = `${c.chapter}:${c.start}${c.end !== c.start ? `-${c.end}` : ''}`;
  const lines = [`[${r.verdict.toUpperCase()}] "${c.span}" -> ${ref}`];
  if (c.invalidReason) lines.push(`  invalid reference: ${c.invalidReason}`);
  for (const n of c.notes) lines.push(`  note: ${n}`);
  if (r.error) lines.push(`  error: ${r.error}`);
  if (r.judgement) {
    const j = r.judgement;
    lines.push(`  cite=${pct(j.citeProbability)} kind=${j.kind} (${pct(j.kindConfidence)}) quoted=${pct(j.quotedProbability)}`);
  }
  if (r.fetched) {
    if (!r.fetched.ok) lines.push(`  fetch failed: ${r.fetched.error}`);
    else {
      lines.push(`  source: ${r.fetched.source}, retrieved ${r.fetched.retrievedAt}`);
      for (const w of r.fetched.warnings) lines.push(`  warning: ${w}`);
      for (const v of r.fetched.verses) {
        lines.push(`  ${c.chapter}:${v.citedVerse} (Al Islam v=${v.alIslamV}, v_=${v.alIslamVUnderscore})`);
        lines.push(`    ${v.arabic}`);
        for (const [ed, t] of Object.entries(v.translations)) lines.push(`    [${ed}] ${t}`);
      }
    }
  }
  if (r.quoteChecks?.length) {
    const best = [...r.quoteChecks].sort((a, b) => b.similarity - a.similarity)[0];
    lines.push(`  quote check (heuristic): match=${best.quoteMatch} similarity=${best.similarity.toFixed(2)} contained=${best.contained}`);
    lines.push(`    quoted: ${best.quoted}`);
  }
  return lines.join('\n');
}

async function main() {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      file: { type: 'string' },
      editions: { type: 'string', default: 'en' },
      accept: { type: 'string' },
      reject: { type: 'string' },
      json: { type: 'boolean', default: false },
      help: { type: 'boolean', short: 'h', default: false },
    },
  });
  if (values.help) return void console.log(USAGE);

  let text: string;
  if (values.file) text = readFileSync(values.file, 'utf8');
  else if (positionals.length) text = positionals.join(' ');
  else if (!process.stdin.isTTY) text = await readStdin();
  else return void console.log(USAGE);

  const thresholds = {
    accept: values.accept !== undefined ? Number(values.accept) : DEFAULT_THRESHOLDS.accept,
    reject: values.reject !== undefined ? Number(values.reject) : DEFAULT_THRESHOLDS.reject,
  };
  const out = await checkText(text, { editions: parseEditions(values.editions as string), thresholds });
  if (values.json) console.log(JSON.stringify(out, null, 2));
  else if (!out.results.length) console.log('No candidate Quran references found.');
  else {
    console.log(out.results.map(render).join('\n\n'));
    console.log(`\ncontainsCitation: ${out.containsCitation}`);
  }
}

main().catch(e => {
  console.error(e instanceof Error ? e.message : String(e));
  process.exit(1);
});
