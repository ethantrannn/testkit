# Metric definitions

Exactly how `scripts/metrics.py` computes each number, so the report can be explained and challenged.

## Selection

- A run's date is the earliest `Executed: YYYY-MM-DD` in its `results/*.md`, else `Created:` in `plan.md`, else the date `report.md` was last modified.
- `--from/--to` select runs whose date is inside the range (inclusive). `--runs` selects by id. `--all` takes every run.
- A bug belongs to the selection when its `ticket` equals the `Ticket:` of a selected run's plan (default: the RUN_ID), or its id starts with `BUG-<RUN_ID>-`. Bugs of other tickets are ignored even if they were updated in the period.

## Execution

| Field | Definition |
|---|---|
| `planned` | `### TC-…` headings in `cases/*.md` |
| `executed` | cases with result PASS or FAIL |
| `pass_rate` | PASS / executed |
| `fail_rate` | FAIL / executed |
| `blocked_rate` | BLOCKED / planned |
| `execution_rate` | executed / planned |
| `not_run` | planned cases with no row in any results file |

## Acceptance criteria

ACs are the `- AC-n: …` lines under `## Acceptance criteria` in `plan.md`. A case covers an AC when its `Requirement:` names it or the stream's `## Traceability` table maps the AC to it.

| AC status | Meaning |
|---|---|
| `PASS` | every covering case PASSED |
| `FAIL` | at least one covering case FAILED |
| `PARTIAL` | some covering cases passed, others BLOCKED/SKIPPED/not run |
| `NOT RUN` | covered, none executed |
| `NOT COVERED` | no case covers it — always call these out |

`coverage_rate` = covered / total ACs; `pass_rate` = ACs with status PASS / total ACs.

## Defects

- Counted bugs exclude `duplicate` (reported separately as `duplicates`). `wont_fix` bugs are counted but treated as closed.
- `by_component`: the bug's `component` frontmatter field if present, else `<RUN_ID> <stream title>` of the bug's `test_case`. Encourage teams to fill `component` so areas are comparable across tickets.
- `density`: bugs of the ticket per 10 executed cases, and per AC. Compare tickets of similar size only.
- `reopen_rate`: bugs with at least one `reopened` History line / bugs with at least one `fixed` line.
- `mean_days_to_fix`: every `open`/`reopened` → next `fixed` interval in History, averaged (a reopened bug contributes several samples).
- `mean_days_to_verify`: the latest `fixed` → `verified` interval; a `reopened` in between cancels it.
- `open_aging`: bugs not in `verified`/`wont_fix`/`duplicate` (so `fixed`-but-not-verified counts as open), by days since `found_at` (or the first History date) at `--today`: 0-2, 3-7, 8-14, 15-30, >30.
- Time metrics only use dated History lines (`- YYYY-MM-DD <status> — …`). Bugs without them are listed in `warnings`.

## Automation

From `qa/automation/coverage.md` (the `testkit-automate` skill), rows of the selected runs only: `automated_rate` = automated / (all rows − not-eligible).

## Risky areas

Score per component: for each bug, severity weight (blocker 8, critical 5, major 3, minor 1, trivial 0.5) if open, 30 % of it if closed; +2 per reopen; +1 per FAILED case and +0.5 per BLOCKED case of the same stream. Top 5 by score, with the reasons that produced the score. It is a ranking aid, not a measurement: say so if someone treats it as one.

## Reading the numbers responsibly

- Small samples: with fewer than 5 fix samples, write "n = 3" next to a mean instead of drawing conclusions.
- Pass rate depends on what was tested: a high pass rate with `NOT COVERED` ACs is not a good sign.
- Density per ticket rewards writing fewer cases; always read it next to AC coverage.
