---
name: testkit-metrics
description: Sprint or release quality report across testkit runs — pass/fail/blocked rates, AC coverage, defects by severity/status/ticket/component, defect density, reopen rate, mean time to fix and to verify, open bug aging, automation coverage and top risky areas — rendered as markdown, Word (.docx), PowerPoint slides (.pptx, native charts) and optionally Excel. Use when the user asks for a sprint/release/quality report, QA metrics, test summary across tickets, KPI slides, "báo cáo chất lượng", "báo cáo sprint", "thống kê bug", "slide báo cáo test", or before a release go/no-go meeting.
argument-hint: "<name> (--from YYYY-MM-DD --to YYYY-MM-DD | --runs RUN_ID… | --all) [--formats md,docx,pptx,xlsx]"
---

# testkit metrics

Numbers come from a script, not from reading files by eye: `metrics.py` scans the runs and bugs and writes `metrics.json`; `build_models.py` turns it into the markdown report and the models for Word, slides and Excel; renderers produce the files. Your job is to choose the scope, read the numbers, write the findings, and check every output visually.

```bash
SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)   # the skills folder testkit installed into
```

## 1. Scope

Ask (or take from the arguments) a report **name** (`sprint-46`, `release-2.3`) and the selection:

- date range `--from/--to` (sprint dates), or
- `--runs PROJ-123 PROJ-130 …` (release scope; take the ticket list from the release plan or tracker), or
- `--all`.

Output folder: `qa/reports/<name>/` (slug the name: lowercase, hyphens). Language: `project.language` from `qa/config.yml` (`en` and `vi` labels are built in).

## 2. Compute

```bash
python3 $SK/testkit-metrics/scripts/metrics.py --from 2026-11-03 --to 2026-11-14 --out qa/reports/sprint-46/metrics.json
```

The definitions of every field are in `references/metric-definitions.md`; read it before explaining a number to anyone. The script prints a one-line summary and lists data problems under `warnings` (runs without results, bugs without History, plans without ACs). Fix what you can (e.g. a missing `Executed:` line) or mention them in the report.

Sanity-check before writing anything: totals per run match the results files you would expect, bug counts match `qa/bugs/index.md`, and no run is missing from the selection.

## 3. Findings

Read `metrics.json` and write `qa/reports/<name>/findings.json`:

```json
{
  "summary": "optional — one paragraph replacing the generated summary",
  "findings": ["Payments is the riskiest area: BUG-… was reopened twice.", "AC-4 of PROJ-101 has no test case."],
  "next_steps": ["Verify BUG-… before the release branch is cut.", "Write cases for PROJ-101 AC-4."]
}
```

3–5 findings, each tied to a number in the report (not opinions), and 2–5 concrete next steps with an owner role where obvious. Call out: `NOT COVERED` ACs, open blocker/critical bugs, reopen rate above ~20 %, bugs open longer than 14 days, `fixed` bugs waiting for verification, BLOCKED cases, and a low automation share of P0 cases. Mind small samples (see the reference).

## 4. Render

```bash
R=qa/reports/sprint-46
python3 $SK/testkit-metrics/scripts/build_models.py $R/metrics.json --name "Sprint 46" --lang en --findings $R/findings.json
# -> $R/quality-report.md, report-docx.json, deck.json, workbook.json

uv run $SK/testkit-export/scripts/build_docx_report.py $R/report-docx.json $R/sprint-46-quality.docx
uv run $SK/testkit-metrics/scripts/build_pptx_deck.py $R/deck.json $R/sprint-46-quality.pptx --split $R/preview
uv run $SK/testkit-export/scripts/build_xlsx.py $R/workbook.json $R/sprint-46-quality.xlsx     # optional Excel
```

- `quality-report.md` is always produced; it is the version people read in the repo.
- Word and Excel use the shared renderers of the `testkit-export` skill (same colours and statuses as run reports). If `build_xlsx.py` is not installed, skip Excel and say so.
- Slides: `build_pptx_deck.py` (python-pptx, pinned) renders the deck model — title slide, KPI tiles, native PowerPoint charts (editable data), tables with coloured status cells (long tables continue on extra slides), and findings/next steps. Its docstring documents the model; you can edit `deck.json` before rendering (reorder slides, add `notes` for the speaker, add a `chart` slide, change `theme.primary` to the company colour). Keep one message per slide and at most 6 KPI tiles.

## 5. Check (required)

Follow the QA steps of the `pptx` and `docx` skills where the tools exist:

1. **Validate**: `uv run --with lxml --with defusedxml python $SK/pptx/scripts/office/validate.py $R/<file>.pptx` and the same with `$SK/docx/scripts/office/validate.py` for the `.docx`. Both must print `All validations PASSED!`.
2. **Content**: `uv run --with python-pptx==1.0.2 --with lxml --with defusedxml python $SK/pptx/scripts/slide_text.py $R/<file>.pptx` — every slide has its title, numbers and chart data; no leftover placeholder text.
3. **Look at every slide and the first Word page.**
   - LibreOffice installed: convert with `$SK/pptx/scripts/office/soffice.py --headless --convert-to pdf` and `pdftoppm -jpeg -r 80`, then open each image (see the `pptx` skill, "Converting to Images").
   - macOS without LibreOffice: `qlmanage -t -s 1400 -o $R/preview $R/preview/slide-*.pptx` (the `--split` decks give one preview per slide) and `qlmanage -t -s 1400 -o $R $R/<file>.docx` for page one. Quick Look ignores per-point chart colours and bar-axis order, and draws white gaps between table cells; those are not defects in PowerPoint.
   - Otherwise say the visual check was skipped.
4. Fix the model (shorter labels, fewer bullets, split a table) and re-render when text overflows a tile or box, a title wraps, a table runs off the slide, or a chart is empty.

## 6. Report back

Paths of `quality-report.md`, `.docx`, `.pptx` (and `.xlsx`), the summary line and the findings, data warnings, and whether the visual check ran (and how). Do not send or upload the files anywhere without asking.
