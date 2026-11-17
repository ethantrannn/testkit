---
name: testkit-plan-release
description: Write a release or sprint level test plan and strategy across many tickets — scope in/out, ticket list with an impact × likelihood risk matrix, test types per area (functional, API, regression, non-functional, UAT), environments and data, entry/exit criteria, effort estimate per ticket, schedule, roles, deliverables and links to each ticket's testkit run. Writes qa/releases/<RELEASE>/test-plan.md, optionally a Word version. Use when the user gives a fix version, sprint, JQL or a list of tickets and asks for a test plan, test strategy or estimate, "lập kế hoạch kiểm thử", "test plan cho release", "kế hoạch test sprint", "ước lượng effort test".
argument-hint: "<fix version | sprint | JQL | ticket keys/files ...> [--name <RELEASE>] [--docx]"
---

# testkit release test plan

One plan for a whole release or sprint. It does not test anything itself: per-ticket work is done by `testkit-run`, and this plan links to those runs.

## 0. Prepare

1. Read `qa/config.yml`: `project`, `environments`, `default_environment`, `accounts.strategy`, `tracker`, `release` (estimation settings, optional — see below). If it is missing, tell the user to run `testkit init` and stop.
2. `RELEASE` = `--name`, else the fix version or sprint name made path-safe (`2026.11`, `sprint-23`). Create `qa/releases/<RELEASE>/`. If `test-plan.md` exists, update it in place: keep its version line, bump the version and add what changed under *Assumptions, dependencies, open questions*.
3. Commands run from the project root with:
   `SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)   # the skills folder testkit installed into`

## 1. Collect the tickets

- **Fix version / sprint / JQL** with the Atlassian tools: search with JQL (`project = PROJ AND fixVersion = "2026.11"`, or `sprint = 123`, or the user's JQL), fields: key, summary, issue type, priority, status, components, labels, story points, assignee, linked issues. Page through all results. Read the description of each ticket briefly (and its comments for high-priority ones) — enough to rate impact and spot non-functional needs; do not do a full spec review here.
- **Without the Atlassian tools**: ask the user for a list of keys with titles, or a CSV export of the Jira search (Jira → Filters → Export → CSV), and read that.
- **Files / pasted list**: one ticket per file or line.

Show the user the list (key, title, type, priority, status) and ask what is out of scope if anything looks like it (won't fix, done in a previous release, no QA needed). Do not wait if the scope is obvious.

## 2. Gather what testkit already knows per ticket

For each ticket key look for, and link if present:

- `qa/specs/<KEY>/review.md` — readiness verdict, risks, open `high` questions (raise likelihood when `NOT READY` or `NEEDS CLARIFICATION`).
- `qa/runs/<KEY>/plan.md` — stream count, risk per stream (basis `plan`).
- `qa/runs/<KEY>/cases/*.md` — count `### TC-` headings (basis `cases`).
- `qa/runs/<KEY>/report.md` — verdict; `qa/bugs/index.md` — open bugs for the ticket.
- `qa/uat/*/` — UAT that covers it.

## 3. Rate risk

For each ticket set `impact` and `likelihood` to `low | medium | high` with a one-line reason:

- **Impact** — high: money, payments, personal data, security, legal/regulatory, the core flow most users use, data migration; medium: a feature used regularly, a workaround exists; low: cosmetic, admin-only, rarely used.
- **Likelihood** — high: new or rewritten code, many components or services, a third-party integration, spec `NOT READY`, history of bugs in the area, rushed timeline; medium: a moderate change to existing code; low: small, isolated change (copy, config).

Score = impact × likelihood (1–9): `high` ≥ 6, `medium` 3–4, `low` ≤ 2. High-risk tickets get more streams, regression around them and UAT; low-risk ones may get a smoke check only — say which.

## 4. Estimate

Write `qa/releases/<RELEASE>/tickets.json` (format in the script's `--help`): every ticket with `impact`, `likelihood`, and `streams`/`cases`/`basis` when known from step 2. Put the estimation settings from `qa/config.yml` (`release.*`) under `assumptions`, plus `regression_hours` and `uat_hours` you estimate for the release (say how: e.g. regression = cases in the regression scope × execute minutes). Then:

```bash
uv run $SK/testkit-plan-release/scripts/estimate.py qa/releases/<RELEASE>/tickets.json \
  qa/releases/<RELEASE>/estimate.md --json qa/releases/<RELEASE>/estimate.json --lang <vi|en>
```

It writes the risk matrix and the estimate table (design, review, execute, retest hours per ticket, totals, person-days, assumptions). Copy them into the plan unchanged; do not do the arithmetic yourself. If the total does not fit the schedule, say so and propose cuts by risk (lowest first), never silently.

## 5. Write `qa/releases/<RELEASE>/test-plan.md`

Follow `assets/test-plan-template.md`, in `project.language`; keep IDs, statuses, risk levels and field names in English. Rules:

- **Scope**: every ticket is in or out, with the reason for out.
- **Test approach per area**: group tickets by component/feature. Functional = `testkit-run` per ticket. API, regression, non-functional and UAT only where the risk or the ticket asks for it; non-functional and heavy tests only on environments where `qa/config.yml` enables them, never on production.
- **Environments and data** come from `qa/config.yml`; list missing ones as dependencies, never invent URLs.
- **Entry/exit criteria**: start from the template defaults and adjust to the release (stricter for high-risk releases).
- **Schedule**: real dates from the user or the sprint/fix version dates (Atlassian tools); if unknown, relative days (D1, D2 …) and ask.
- **Roles**: names only if the user or the tickets give them; otherwise roles with blanks.
- **Ticket runs**: relative links from `qa/releases/<RELEASE>/` to `../../specs/<KEY>/review.md` and `../../runs/<KEY>/{plan,report}.md`; `not started` when missing.

Then tell the user: number of tickets in/out, high-risk tickets, total effort in person-days, the next step for each ticket without a run (`/testkit-spec-review <KEY>` for unclear specs, `/testkit-run <KEY>`), and open questions.

## 6. Optional Word export

When the user asks (`--docx`) or `report.formats` contains `docx`: build `qa/releases/<RELEASE>/export/test-plan.json` for the `testkit-export` renderer (model format in the `testkit-export` skill, section 2) and render it:

```bash
uv run $SK/testkit-export/scripts/build_docx_report.py \
  qa/releases/<RELEASE>/export/test-plan.json qa/releases/<RELEASE>/export/<RELEASE>-test-plan.docx
```

Model: `title` "Kế hoạch kiểm thử — <RELEASE>" / "Test plan — <RELEASE>", `meta` = release, product, version, status, prepared by/date; `"landscape": true` (the estimate table is wide); one level-1 section per plan section; every markdown table becomes a `table` block (risk matrix widths `[2, 2, 2, 2]`, estimate table: keep Ticket, Title, Risk, Streams, Cases, Total h, widths `[2, 5, 1.5, 1.5, 1.5, 1.5]` — the full hour split stays in the markdown), bullet lists become `bullets`, the ticket run links become plain paths. Risk words (`high`…) are not colour-coded by the renderer; put verdicts (`READY`, `NOT READY`) in their own column so they are. Validate and look at it as the `testkit-export` skill says (validate.py, page images or `qlmanage`).

## Config (optional, `qa/config.yml`)

```yaml
release:
  hours_per_day: 6                 # productive testing hours per person-day
  minutes_per_case: {design: 10, review: 3, execute: 8}
  retest_buffer: 0.2               # share of execution time for bug retests
  default_size:                    # streams × cases per stream when a ticket has no plan yet
    high:   {streams: 3, cases_per_stream: 12}
    medium: {streams: 2, cases_per_stream: 8}
    low:    {streams: 1, cases_per_stream: 5}
```

## Rules

- Read-only towards Jira; never change tickets, versions or sprints.
- Never invent tickets, dates, names or numbers. Unknowns go to open questions.
- Do not start `testkit-run` for the tickets yourself; list it as the next step and let the user decide.
