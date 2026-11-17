---
name: testkit-spec-review
description: Review requirements before or while a feature is built — reads a ticket and its specs (Word .docx, PDF, Confluence pages, Figma designs, code), extracts numbered acceptance criteria and lists ambiguities, contradictions between docs, design and code, missing cases (errors, permissions, limits, empty states, Vietnamese text, time zones), testability issues, risks and a ranked question list for PO/dev. Writes qa/specs/<SPEC_ID>/review.md, which test-lead reuses when planning the ticket. Use when the user asks to review a spec/ticket/requirement, "phân tích yêu cầu", "review spec", "rà soát tài liệu", "đọc đặc tả", "câu hỏi cho PO", or before /testkit-run on a ticket with a long or unclear spec.
argument-hint: "<ticket key | URL | spec file ...> [--confluence <url>] [--figma <url>] [--id <SPEC_ID>] [--update]"
---

# testkit spec review

Static review of requirements: no browser, no test execution. The output is a review file the team can answer and that `test-lead` reuses, so the questions are asked once, early.

## 0. Prepare

1. Read `qa/config.yml` (`project.language`, `docs.paths`, `code.paths`, `tracker`). If it is missing, tell the user to run `testkit init` and stop.
2. `SPEC_ID` = the ticket key (`PROJ-123`) — the same ID `testkit-run` uses as `RUN_ID`, so the plan finds the review. Without a ticket: a short slug plus date (`checkout-coupon-261117`), or `--id`.
3. Create `qa/specs/<SPEC_ID>/sources/`. If `review.md` already exists, this is an update: keep every existing ID (AC, A, C, M, T, R, Q), fold in answers the team wrote in the *Answer* column, mark resolved items `(resolved <date>: <answer>)` instead of deleting them, and add a *History* line.
4. Commands below run from the project root with:
   `SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)   # the skills folder testkit installed into`

## 1. Collect sources

Convert every source once into `qa/specs/<SPEC_ID>/sources/` so the review, the plan and the writers all cite the same text. Record each one in the *Sources* table with its version or date.

- **Ticket** (Jira key/URL): with the Atlassian tools if available, read the issue with comments, attachments list and linked issues. Save the description, ACs and relevant comments to `sources/<KEY>.md`. Without the tools, ask the user to paste the ticket.
- **Word** (`.docx`): follow the `docx` skill:
  `pandoc -s --track-changes=all -t gfm --extract-media=qa/specs/<SPEC_ID>/sources "<file>.docx" -o "qa/specs/<SPEC_ID>/sources/<name>.md"`.
  Legacy `.doc` first: `uv run --with lxml --with defusedxml python $SK/docx/scripts/office/soffice.py --headless --convert-to docx <file>.doc` (needs LibreOffice). Tracked changes and comments are questions, not requirements.
- **PDF**: `uv run $SK/testkit-spec-review/scripts/pdf_to_md.py "<file>.pdf" "qa/specs/<SPEC_ID>/sources/<name>.md"` (text and tables per page, `## Page N` markers). If it warns about pages without text (scanned), follow the `pdf` skill: render those pages to images (`$SK/pdf/scripts/convert_pdf_to_images.py`) and look at them, or OCR them.
- **Confluence**: with the Atlassian tools, fetch the page (and child pages the user names) as markdown or storage format, convert to markdown and save `sources/confluence-<page-id>-<slug>.md` with the URL and page version at the top. Without the tools, ask the user to export the page (`••• → Export → Word` or PDF) and process the file as above.
- **Figma**: if Figma tools are available, for each frame/screen the ticket touches get its text content (labels, buttons, messages, placeholders), states/variants and a screenshot; save `sources/figma/<frame>.png` and `sources/figma/<frame>.md` (text inventory). Without Figma tools, skip the design check and write so in *Design check* and *Sources* ("not reviewed"); ask the user for exported PNG/PDF frames if the design matters.
- **Code**: in `code.paths`, search for the routes, API handlers, validators, permission checks, enums, feature flags and i18n message files the ticket touches. Do not read the whole repo. Note `file:line`.
- **Docs** in `docs.paths` that the ticket links or that match its feature.

If a linked attachment cannot be downloaded, ask the user for the file. Never invent content for a source you could not read.

## 2. Analyse

Read `references/review-checklist.md` and go through it for every requirement:

1. Extract acceptance criteria `AC-1…` with sources; rate testability.
2. Ambiguities — quote the text, give the readings.
3. Contradictions — ticket vs documents, documents vs design, documents vs code, inside one document.
4. Missing cases — errors, permissions, limits, empty states, states/lifecycle, data rules, Vietnamese text/i18n, time zones and dates, notifications, integrations, non-functional.
5. Testability issues and what would fix them.
6. Risks with impact × likelihood and the test focus.
7. Questions, ranked by impact (high → low), each linked to the findings and ACs it settles, addressed to PO, dev or design.

Write findings, not essays: one table row each. Every finding cites its source. If docs and code disagree, do not pick a winner; ask.

Readiness verdict: `READY` (no high questions), `NEEDS CLARIFICATION` (high questions, but test design can start on the rest), `NOT READY` (core behaviour undefined or contradictory).

## 3. Write `qa/specs/<SPEC_ID>/review.md`

Use `assets/review-template.md`. Write in `project.language`; keep IDs, statuses, impact levels and field names in English. Then tell the user: readiness, counts, the top 5 questions, and the path.

## 4. Optional: post the questions to Jira

Only if the ticket is in Jira, the Atlassian tools are available and the user says yes after seeing the questions. Post **one** comment on the ticket: a short intro line, the open questions as a numbered list (`Q-1 [high] … — for PO`), and the path of the review file in the repo. Do not post answers, internal notes, credentials or environment URLs. Add a *History* line `posted N questions to <KEY> on <date>`. Re-running the review later posts only new or changed questions, and only after asking again.

## 5. How the review is reused

- `test-lead` (plan mode) reads `qa/specs/<RUN_ID>/review.md` when it exists: it keeps the AC numbering, cites the already converted files in `qa/specs/<RUN_ID>/sources/` instead of converting again, turns answered questions into requirements (source: the answer), copies unanswered `high`/`medium` questions into *Open questions*, and uses the risks for stream risk levels.
- `testkit-plan-release` uses the readiness verdict and the risk table for the ticket's likelihood rating.
- `testkit-uat` reuses the AC list for UAT scenarios.

## Rules

- Read only; never change code, docs or the tracker (except the one Jira comment the user approved).
- Only open environments and hosts listed in `qa/config.yml` if you need to look at the running app; this skill normally does not.
- Do not store secrets or personal data from tickets in `sources/`; replace them with `<redacted>`.
