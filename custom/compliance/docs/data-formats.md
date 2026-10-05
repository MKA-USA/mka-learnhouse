# Yearly data formats (CSV)

All importers are idempotent (re-import = same state), validating, and never fatal: bad rows are skipped and
reported as issues (printed, and listed in `out/data-gap-report.md` via `gap-report --data <dir>`).
CSV is RFC 4180 (UTF-8, BOM ok, quoted multi-line cells ok). Header names are case-insensitive.
Spreadsheet errors (`#REF!`, `#N/A`, `#VALUE!`, ...) in any cell are treated as blank and reported (`sheet-error`).
A row with fewer/more cells than the header is skipped (`shifted-row`).

## dept_plans.csv  (`provisioner import dept-plans <file> --cycle 2026-27`)
| column | required | notes |
|---|---|---|
| department | yes | slug, name, translation or alias (`Tarbiyat` -> tarbiyyat). Unknown -> `unknown-department`, row skipped |
| level | yes | `all`, `national`, `region`, `majlis` (blank = `all`) |
| responsibilities_md | one of three | Markdown. Converted to ProseMirror at import (headings, lists, tables, bold/italic, links) |
| okrs_md | | Markdown; start objectives with `Objective N: ...` (the QUIZ is built from these lines) |
| resources_md | | Markdown |
| updated_by | no | free text |
| stale | no | `true` marks carried-over text; the course shows "Last year's content, update pending" |

Key: (cycle, department, level). Duplicate rows: later wins (`duplicate-key`). All-empty rows: `empty-plan`.

## directory_overrides.csv  (`import overrides`)
Corrections to the generated roster (name and/or mailbox) for one role slot.
| column | notes |
|---|---|
| department | blank for roles without a department (qaid, naib qaid, sadr) |
| majlis | canonical name or slug alias (`syracuse` -> Syracuse-Binghamton, logged `slug-alias`). Blank + region = regional role; both blank = national |
| region | optional for Majlis rows (validated against the fork map) |
| role | optional; required when two roles share a slot (Atfal: `nazim_atfal` / `murabbi_atfal`) |
| learner_email | optional; must be `@mkausa.org` or `@atfalusa.org` (else `foreign-domain` warning) |
| person_name | optional |
| note | optional |

Checks: mailbox prefix must belong to the row's department. The known Atfal/Amoor-e-Tuluba column swap is auto-corrected from the mailbox
(`swapped-columns`); any other mismatch skips the row (`department-mismatch`). Also: `email-majlis-mismatch`, `duplicate-mailbox`, `unknown-majlis`, `bad-email`, `override-no-match`, `override-ambiguous`.
Overridden roster rows get `source = override` and are never overwritten by `roster` regeneration.

## names.csv  (`import names`, optional enrichment)
`email,name`. Unknown mailboxes are counted, not fatal. Placeholder names (`N/A`, `TBD`, `missing`) -> `missing-name`;
an email in the name column -> `shifted-row`.

## Commands
```
bun run start roster [--cycle 2026-27]
bun run start import dept-plans|overrides|names <file> [--cycle]
bun run start seed-thinkific [--dir <thinkific data>]    # 2025-26 stale plans, source thinkific-2025-26
bun run start gap-report [--cycle] [--data <dir with the CSVs>] [--carry-over 2025-26]
```
(run from `apps/provisioner`; outputs go to `custom/compliance/out/`)
