---
name: bug-reporting
description: Bug report format, severity rules, bug IDs and the bug lifecycle (open → fixed → verified/reopened) used by testkit. Load before filing a bug from a failed test case, updating the bug index, or verifying a fix.
---

# Bug reporting

## Where bugs live

- One file per bug: `qa/bugs/<BUG_ID>.md`. Bugs outlive runs, so they are not inside `qa/runs/`.
- Index: `qa/bugs/index.md`, one table row per bug. Only the **test-lead** (or the orchestrating session) edits the index, after executors finish, so parallel executors never write the same file.
- If `qa/config.yml` sets `tracker: jira` and the coding agent has Atlassian (Jira) tools, the lead also creates the Jira issue and writes its key into the bug's `tracker_key` (see "Pushing bugs to Jira"). Ask the user before creating issues in an external tracker for the first time in a session.

## Bug ID

`BUG-<RUN_ID>-<STREAM_ID>-<NN>`, e.g. `BUG-PROJ-123-S2-01`. The stream prefix keeps IDs unique when executors run in parallel. Before filing, read `qa/bugs/index.md` and search `qa/bugs/` for the same symptom; if the bug already exists and is open, add the new TC to its `related_cases` instead of filing a duplicate. If it exists with status `verified`, file a new bug and link the old one as a regression.

## Bug file

```markdown
---
id: BUG-PROJ-123-S2-01
title: Saving a profile with a 256-character name returns 500
status: open            # open | fixed | verified | reopened | wont_fix | duplicate
severity: major         # blocker | critical | major | minor | trivial
priority: P1            # P0 | P1 | P2
ticket: PROJ-123
test_case: TC-S2-004
component:              # optional product area (e.g. Checkout); makes per-area metrics comparable
related_cases: []
environment: staging
build: <commit, version or deploy id shown by the app, if available>
browser: browser-use <version> (isolated Chrome <version>), 1280x720
found_by: test-executor
found_at: 2026-11-17
tracker_key:            # e.g. JIRA-456, filled when pushed to a tracker
fixed_in:               # filled by the developer
verified_at:
---

## Summary
One sentence: what is wrong and where.

## Steps to reproduce
1. Log in as `{{member}}`.
2. Open `/settings/profile`.
3. Fill "Display name" with 256 × "a".
4. Click "Save".

## Expected
Inline error "Name must be at most 255 characters" (docs/profile.md#validation). No request is sent.

## Actual
Toast "Something went wrong". `PATCH /api/profile` returns 500.

## Evidence
- Screenshot: `qa/runs/PROJ-123/evidence/S2/TC-S2-004-fail.png`
- Console: `qa/runs/PROJ-123/evidence/S2/TC-S2-004-console.txt`
- Network: `qa/runs/PROJ-123/evidence/S2/TC-S2-004-network.txt`

## Notes
Reproduced 3/3 times. Not reproducible with 255 characters.

## History
- 2026-11-17 open — filed by test-executor (run PROJ-123)
```

## Video evidence

When steps alone do not show the problem (animation, timing, flicker, a race), attach a short video:

- browser-use: `start_recording("<TC_ID>", title="...")` before the steps, `stop_recording()` after; keep the returned folder. agent-browser: `record start <path>.webm` / `record stop`.
- Convert for trackers and chat (most do not preview `.webm`), with ffmpeg:
  ```bash
  ffmpeg -y -i in.webm -c:v libx264 -pix_fmt yuv420p -movflags +faststart -vf "scale='min(1280,iw)':-2" out.mp4
  ffmpeg -y -i in.webm -vf "fps=8,scale='min(960,iw)':-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" out.gif   # under ~10 s only
  ```
- Keep videos under 30 seconds and 20 MB; trim with `-ss <start> -t <seconds>`. Save next to the screenshots as `<TC_ID>.mp4` and list it under `## Evidence`.

## Pushing bugs to Jira

Field mapping comes from `jira:` in `qa/config.yml`:

```yaml
jira:
  project_key: PROJ
  issue_type: Bug
  severity_field: priority          # Jira field that holds severity: priority, or a custom field id like customfield_10042
  severity_map: {blocker: Highest, critical: High, major: Medium, minor: Low, trivial: Lowest}
  components: []                    # default components, e.g. [Checkout]
  labels: [testkit]
  link_type: Relates                # link the bug to its ticket with this link type
  attach_evidence: true             # upload the screenshots/video listed under Evidence
```

- Summary = bug title; description = Summary, Steps to reproduce, Expected, Actual, Environment/build, and the bug file path. Never include passwords or tokens.
- Set severity through `severity_field` + `severity_map`, labels and components, and link the issue to `ticket` with `link_type`.
- Attach evidence only if `attach_evidence` is true and the tools support attachments; otherwise list the evidence paths in the description.
- Write the returned key into `tracker_key` and add a `## History` line. When verify mode changes status, comment on the issue with the result and evidence; transition it only if `tracker_transitions: true`.
- If the custom field id is unknown, look it up with the Jira tools (field metadata for the project and issue type) and tell the user which id to put in the config.

## Severity

| Severity | Meaning |
|---|---|
| blocker | Main flow cannot be completed; no workaround; or data loss / security hole |
| critical | Important feature broken; workaround is unreasonable |
| major | Feature works incorrectly in a common case; workaround exists |
| minor | Edge case or validation gap with low impact |
| trivial | Cosmetic, copy, alignment |

## Before filing (avoid false bugs)

1. Reproduce at least twice from a clean state (new session or reload).
2. Confirm the expected result really comes from the docs/ticket. If the docs are silent, it is a **question**, not a bug: record it in the results file under `Questions` instead.
3. Rule out test problems: wrong data, stale `@ref`, slow network, missing precondition. If the cause is the test, mark the case `BLOCKED` and explain.

## Lifecycle

```
open ──(developer fixes, sets status: fixed + fixed_in)──▶ fixed
fixed ──(executor re-tests: pass)──▶ verified
fixed ──(executor re-tests: still fails)──▶ reopened ──▶ fixed ...
open/reopened ──(product decides)──▶ wont_fix | duplicate
```

Every status change appends one line to `## History` with date, new status, who, and the evidence path. Never delete history lines.

## Verifying a fix

1. Re-run the bug's `Steps to reproduce` exactly, on the environment and build named in `fixed_in` (or the latest build if not given).
2. Re-run the bug's `test_case` and every `related_cases` entry.
3. Run a small regression around the fix: the neighbouring cases in the same stream that touch the same screen or API (at least the P0 ones).
4. Pass everything → `status: verified`, `verified_at: <date>`. Anything still failing that matches the bug → `status: reopened` with new evidence. A *different* failure → keep this bug verified and file a new bug.
