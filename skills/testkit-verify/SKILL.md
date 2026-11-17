---
name: testkit-verify
description: Verify bugs that developers marked as fixed — test-executor re-runs the reproduction steps, the original and related test cases plus a small regression, then sets each bug to verified or reopened with evidence. Use when the user says a bug is fixed, "verify bug", "retest", "kiểm tra lại bug", or passes BUG IDs / a ticket whose bugs were fixed.
argument-hint: "[BUG_ID ... | --ticket <RUN_ID> | --all-fixed] [--env <name>]"
---

# testkit verify

## 1. Select bugs

- Explicit IDs → those bugs.
- `--ticket <RUN_ID>` → bugs in `qa/bugs/` with that `ticket` and `status: fixed`.
- `--all-fixed` or no argument → every bug with `status: fixed`.

If the user says a bug is fixed but its file still says `open`/`reopened`, ask for the fix reference (commit, PR, build), then set `status: fixed`, `fixed_in: <ref>` and add a `## History` line "fixed — reported by user" before verifying.

If `tracker: jira`, also look at the linked issue: if Jira says it is resolved but the file is not `fixed`, list it and ask the user whether to include it.

Show the user the list (ID, title, severity, fixed_in) and the environment you will verify on.

## 2. Group and dispatch

Group bugs by `ticket` + stream (the stream is in the bug ID). Each group goes to one `test-executor` agent (started as described in `testkit-run`, "Starting role agents") in mode `verify`, with: project root, environment and base URL, the bug IDs, and the path to the original `cases/<STREAM_ID>.md` so it can find related and regression cases. Groups run in parallel (cap at `execution.max_parallel_streams`); bugs that touch global settings run alone.

## 3. Consolidate

When all executors return:

1. Start `test-lead` (mode report) only if a run report needs updating; otherwise update `qa/bugs/index.md` yourself: new `Status` for each bug, and add rows for any new bugs the executors filed.
2. Tell the user: a table `BUG_ID | before | after | evidence`, the reopened bugs first with one line on what still fails, and any new bugs found during regression.

After updating bugs, record each status change with `testkit-knowledge` ("Pipeline hooks" → bug status change). When a bug is closed as `wont_fix` or the user explains why a behaviour is intended, record that ruling as a decision with `testkit-knowledge` (`remember`), so the same behaviour is not reported again.
