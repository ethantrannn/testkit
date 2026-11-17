---
name: testkit-run
description: Run the full testkit QA pipeline for a ticket — test-lead plans independent streams, script-writer writes cases per stream in parallel, test-reviewer reviews them (with revision rounds), test-executor runs approved streams in a browser in parallel waves, then test-lead consolidates bugs and the report. Use when the user gives a ticket (Jira key/URL, issue link, spec file, pasted requirement) and wants it tested, or says "test this ticket", "chạy test", "viết và chạy test case".
argument-hint: "<ticket key | URL | file> [--env <name>] [--streams S1,S2] [--only plan|write|review|execute|report]"
---

# testkit run

You (the main session) are the orchestrator: **you** start every role agent; `test-lead` only plans and reports. Do not delegate orchestration to a role agent: several tools (Claude Code, Gemini CLI) do not let a subagent start another one.

## Starting role agents

The four roles (`test-lead`, `script-writer`, `test-reviewer`, `test-executor`) are installed as custom subagents for the project's coding agent. Start one with a self-contained prompt (see "Every agent prompt" below) and wait for its result:

| Coding agent | How to start the role `test-lead` | Role definition |
|---|---|---|
| Claude Code | Agent/Task tool, `subagent_type: "test-lead"` | `.claude/agents/test-lead.md` |
| Codex | Spawn the custom agent `test-lead` and wait for it (the project must be trusted in Codex) | `.codex/agents/test-lead.toml` |
| Cursor | Task tool with the subagent `test-lead` | `.cursor/agents/`, `.claude/agents/` or `.codex/agents/` |
| Gemini CLI | Delegate to the subagent `test-lead` (the folder must be trusted in Gemini CLI) | `.gemini/agents/test-lead.md` |
| GitHub Copilot | Run the custom agent `test-lead` | `.github/agents/test-lead.agent.md` |
| No subagent support | Do the role yourself: read its role definition file and follow it, one stream at a time | any of the files above |

If your spawn tool cannot pick a custom agent by name (some Codex versions only offer a generic sub-agent), start a generic sub-agent and begin its prompt with: `Your role: <role>. Read <role definition file> and follow those instructions exactly.` Then add the usual task details.

"In parallel" below means: start several role agents in the same turn when your tool supports it (Claude Code, Codex and Cursor do); otherwise run them one after another. The result files are the same either way.

## 0. Prepare

1. Parse arguments: ticket, `--env` (default `default_environment`), `--streams` (subset), `--only` (one phase).
2. Read `qa/config.yml`. If missing, tell the user to run `testkit init` in the project folder and stop. If it still has example values (`example.com`), run the `testkit-config` skill first.
3. `RUN_ID` = the ticket key (`PROJ-123`); for a file or pasted text, a short slug plus date (`checkout-coupon-261117`). If `qa/runs/<RUN_ID>/` exists, tell the user and continue from the first unfinished phase (see "Resume").
4. Create `qa/runs/<RUN_ID>/{cases,reviews,results,evidence}`.

Every agent prompt you send must contain: project root, `RUN_ID`, `STREAM_ID` where relevant, environment name and base URL, the mode, and the paths to read/write. Agents start with no context except what you send.

If the spec is long, unclear or comes from several documents and `qa/specs/<RUN_ID>/review.md` does not exist yet, suggest running the `testkit-spec-review` skill first; the lead reuses its result.

## 1. Plan — `test-lead` (mode plan)

Start one `test-lead` with the ticket and `RUN_ID`. Wait for it. Then read `plan.md` yourself and show the user a short table: streams, waves, risks, open questions.

If there are open questions that change scope, ask the user now (one question at a time). Otherwise continue without waiting. Record every answer as a decision with `testkit-knowledge` (`remember`, source: the user, today's date) so later runs and other agents do not ask again.

## 2. Write — `script-writer` × streams (parallel)

Start one `script-writer` per stream, in parallel (respect `execution.max_parallel_streams`; queue the rest). Writers of dependent streams can still run in parallel — dependencies matter only at execution.

## 3. Review — `test-reviewer` (pipeline per stream)

As each writer finishes, start a `test-reviewer` for that stream; do not wait for the other writers.

- `APPROVED` → stream is ready to execute.
- `CHANGES_REQUESTED` → start the `script-writer` again for that stream with "revision round: address `reviews/<STREAM_ID>.md`", then review again.
- Stop after `execution.max_review_rounds` rounds (default 2). If still not approved, show the user the open blocking findings and ask: execute anyway, or fix the docs/requirements first.

Collect the reviewers' questions; ask the user only those that block execution.

## 4. Execute — `test-executor` (mode execute, by waves)

Follow the waves in `plan.md`:

- Within a wave, start one `test-executor` per approved stream, in parallel (cap at `max_parallel_streams`).
- Start the next wave only when every stream it depends on has finished. If a stream it depends on has a P0 FAIL, tell the user and ask whether to still run the dependent stream.
- A stream marked "alone" runs with no other executor active.
- `browser.mode: local` drives the user's own Chrome, so run **one executor at a time** whatever the plan says. `browser.mode: cloud` is billed: before the first execution, tell the user how many cloud browsers will run in parallel and get a yes.
- After the last wave, stop every browser session (browser-use): `SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1); $SK/browser-testing/scripts/bu-session.sh stop-all`.

Streams that contain only `Type: api` cases need no browser session and can run in a wider wave (still within `max_parallel_streams`). Pass `--env` on to the executor so API runs and browser runs hit the same environment.

Before the first execution against an environment with `allow_write: true` in this session, tell the user in one line which environment and URL will receive test accounts and data.

## 5. Report — `test-lead` (mode report)

Start `test-lead` in report mode. When it returns, show the user:

- verdict (`READY` / `READY WITH KNOWN ISSUES` / `NOT READY`);
- totals per stream;
- new bugs by severity with file paths;
- blocked cases and what unblocks them;
- open questions;
- path to `qa/runs/<RUN_ID>/report.md`.

For every format listed in `report.formats` besides `markdown` (`docx`, `xlsx`), run the `testkit-export` skill (`report`, `--format <format>`) and give the user the file paths. Otherwise mention once that `testkit-export` makes Word and Excel versions.

The lead's report step also records the run summary and the answered questions in the project knowledge (`testkit-knowledge`).

## 6. Optional follow-ups

Offer these in one line after the report; run them only when the user agrees or `qa/config.yml` asks for them:

- **Automate** (`testkit-automate`): when the verdict is `READY` or `READY WITH KNOWN ISSUES` and `qa/automation/` exists (or the user asks), start a `script-writer` with that skill to turn the executed streams into Playwright specs, then a `test-executor` to run them.
- **Audits** (`quality-audits`): accessibility, performance and visual checks on the screens the ticket changed; load and security checks only where `audits` config allows.
- **UAT** (`testkit-uat`), **user guide / release notes** (`testkit-guide`), **sprint or release metrics** (`testkit-metrics`), **release test plan** (`testkit-plan-release`).

If the lead asks to create Jira issues, ask the user before allowing it.

## Resume

Detect the phase from files: no `plan.md` → plan; a stream without `cases/` → write; without `reviews/` or not `APPROVED` → review; without `results/` → execute; no `report.md` → report. Run only the missing work. With `--only <phase>`, run just that phase for the selected streams.

## Re-running after case fixes

If an executor lists "Case problems", send those lines to the writer as a revision round, re-review, and re-execute only the affected cases by passing their IDs to the executor ("execute only: TC-S2-006, TC-S2-007").
