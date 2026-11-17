---
name: testkit-export
description: Export a testkit run for people and tools outside the repo — Word (.docx) test report with bug evidence, test cases or bug list; Excel (.xlsx) cases, results, bugs or report with filters, status colours and dropdowns; CSV import files for TestRail and Xray (Jira Cloud). Use when the user asks for a Word/Excel report, test-case spreadsheet, bug list to send, import into TestRail or Xray, "xuất báo cáo", "xuất file Word", "xuất Excel", "xuất test case ra Excel", "import TestRail", "import Xray", or when qa/config.yml lists docx/xlsx in report.formats after a run.
argument-hint: "<RUN_ID> [report | cases | bugs | results | all] [--format docx | xlsx | testrail-csv | xray-csv]"
---

# testkit export (.docx, .xlsx, import CSV)

Turn the markdown files of a run into files for people outside the repo. You build a JSON model from the run files and a script renders it with fixed styles, so every export looks the same:

| `--format` | Kinds | Script | Output in `qa/runs/<RUN_ID>/export/` |
|---|---|---|---|
| `docx` (default) | `report`, `cases`, `bugs` | `build_docx_report.py` | `<RUN_ID>-<kind>.docx` |
| `xlsx` | `report`, `cases`, `bugs`, `results` | `build_xlsx.py` (cases via `export_cases.py`) | `<RUN_ID>-<kind>.xlsx` |
| `testrail-csv` | `cases` | `export_cases.py` | `<RUN_ID>-testrail.csv` |
| `xray-csv` | `cases` | `export_cases.py` | `<RUN_ID>-xray.csv` |

`all` = every kind the format supports. With no `--format`, use `report.formats` from `qa/config.yml` (`docx`, `xlsx`), else `docx`.

For anything the Word renderer does not cover (filling a customer's Word template, tracked changes, comments), use the `docx` skill; run its Python scripts as `uv run --with lxml --with defusedxml python $SK/docx/scripts/<script>` because they need those two packages. For editing an existing spreadsheet, use the `xlsx` skill.

Other testkit skills (`testkit-plan-release`, `testkit-uat`) reuse these two renderers with their own models; the model formats below are the contract.

## 1. Inputs

- `RUN_ID`, the kind (`report` default, `cases`, `bugs`, `results`, `all`) and the format.
- Read from `qa/runs/<RUN_ID>/`: `plan.md`, `report.md`, `cases/*.md`, `results/*.md`, and the bug files in `qa/bugs/` whose `ticket` is this run. If `report.md` is missing for a `report` export, tell the user to finish the run first (`/testkit-run <ticket> --only report`).
- Write in `project.language` from `qa/config.yml`. Keep IDs, statuses and severities in English so the colour coding works.
- Run every command from the project root, with the skills folder in `SK`:
  ```bash
  SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)   # the skills folder testkit installed into
  ```

## 2. Word (.docx)

Write `qa/runs/<RUN_ID>/export/<kind>.json`. Format (all block types):

```json
{
  "title": "Báo cáo kiểm thử — PROJ-123",
  "subtitle": "<ticket title>",
  "meta": [["Ticket", "PROJ-123"], ["Môi trường", "staging — https://…"], ["Ngày", "2026-11-17"], ["Kết luận", "NOT READY"]],
  "landscape": false,
  "sections": [
    {"heading": "1. Tổng quan", "level": 1, "blocks": [
      {"type": "paragraph", "text": "…"},
      {"type": "bullets", "items": ["…"]},
      {"type": "numbered", "items": ["…"]},
      {"type": "table", "columns": ["Stream", "Cases", "PASS", "FAIL", "BLOCKED"], "rows": [["S1", "14", "13", "1", "0"]], "widths": [3, 1, 1, 1, 1]},
      {"type": "kv", "rows": [["Severity", "critical"]]},
      {"type": "image", "path": "qa/runs/PROJ-123/evidence/S2/TC-S2-001-fail.png", "caption": "TC-S2-001 — …", "width_cm": 14},
      {"type": "page_break"}
    ]}
  ]
}
```

Cells whose entire text is a status or severity (`PASS`, `FAIL`, `BLOCKED`, `SKIPPED`, `READY`, `NOT READY`, `READY WITH KNOWN ISSUES`, `blocker` … `trivial`, `open`, `fixed`, `verified`, `reopened`) get a colour. Put the status alone in its own column. Image paths are relative to the project root. One line per paragraph or list item; the renderer splits table cell text on `\n`.

### docx `report`

1. **Meta**: ticket, title, environment + base URL, build if known, date, verdict.
2. **Tổng quan / Summary**: one paragraph with the verdict and the reason; totals table per stream and overall (Cases, PASS, FAIL, BLOCKED, SKIPPED).
3. **AC coverage**: table `AC | Test cases | Result`; an AC with no executed case gets `BLOCKED` or `SKIPPED` and a note.
4. **Bugs**: table `ID | Title | Severity | Status | Test case`, sorted by severity. Then, for each blocker/critical/major bug, a level-2 heading with the ID and title, a `kv` block (severity, status, environment, test case), numbered steps to reproduce, expected and actual paragraphs, and its fail screenshot as an `image`.
5. **Blocked cases**: table `Case | Reason | What unblocks it`.
6. **Questions** for product/dev: bullets.
7. **Appendix: results per stream**: one table per stream `Case | Priority | Status | Notes` (no evidence paths; screenshots are already in section 4).

### docx `cases`

Use `"landscape": true`. Per stream: a level-1 heading `<STREAM_ID> — <title>`, the traceability table `Requirement | Source | Test cases`, then one table with columns `ID | Title | Priority | Preconditions | Steps | Expected` and widths `[2, 4, 1, 4, 6, 5]`. Steps and expected results go in one cell each, one item per line (`"1. Open /login\n2. Fill …"`).

### docx `bugs`

Table of all bugs of the run (or every open bug in `qa/bugs/` when the user asks for the full list), then one detail section per bug as in `report` step 4, including minor ones.

### Render and check the .docx

```bash
uv run $SK/testkit-export/scripts/build_docx_report.py \
  qa/runs/<RUN_ID>/export/report.json qa/runs/<RUN_ID>/export/<RUN_ID>-report.docx
```

`uv` installs python-docx (and openpyxl for Excel) into its cache on first use.

Then check the file, following the `docx` skill:

1. Validate: `uv run --with lxml --with defusedxml python $SK/docx/scripts/office/validate.py <file>.docx`. It must print `All validations PASSED!`.
2. Look at it: if LibreOffice is installed, `uv run --with lxml --with defusedxml python $SK/docx/scripts/office/soffice.py --headless --convert-to pdf <file>.docx` and `pdftoppm -jpeg -r 80 <file>.pdf qa/runs/<RUN_ID>/export/page`, then open the page images and look at them. Without LibreOffice on macOS, `qlmanage -t -s 1400 -o qa/runs/<RUN_ID>/export <file>.docx` shows page one (Quick Look ignores fixed table widths, so narrow tables there are not a defect). Otherwise read it back with `pandoc -t plain <file>.docx` and say the visual check was skipped.
3. Fix the model and re-render if text overflows, an image is missing (`[missing image: …]`) or a table is unreadable (too many columns: split it or switch to landscape).

## 3. Excel (.xlsx)

The workbook model and the sheet layout of each kind are in `references/xlsx-model.md`. Read it first.

- `cases`: never build by hand; convert the case files:
  ```bash
  uv run $SK/testkit-export/scripts/export_cases.py --to xlsx-model \
    -o qa/runs/<RUN_ID>/export/cases.xlsx.json qa/runs/<RUN_ID>/cases/*.md
  ```
  Add `--lang en` when `project.language` is not `vi`. Warnings about cases without steps or expected results are writer problems: list them for the user.
- `results`, `bugs`, `report`: write `qa/runs/<RUN_ID>/export/<kind>.xlsx.json` from the run files, following the layouts in the reference.

Render; the script re-opens the file and checks it, and exits non-zero on a problem:

```bash
uv run $SK/testkit-export/scripts/build_xlsx.py \
  qa/runs/<RUN_ID>/export/<kind>.xlsx.json qa/runs/<RUN_ID>/export/<RUN_ID>-<kind>.xlsx
```

It must print `check: no formulas` and `check: OK`. The workbooks hold values only; do not add formulas. If you ever must (a customer template), follow the `xlsx` skill: recalculate with its `recalc.py` (needs LibreOffice) and fix every error it lists. To look at the result on macOS: `qlmanage -t -s 1400 -o qa/runs/<RUN_ID>/export <file>.xlsx` renders the top-left of the first sheet; open the image and look at it. Otherwise read it back with `uv run --with openpyxl==3.1.5 python -c` and say the visual check was skipped.

## 4. TestRail and Xray import files

Formats, wizard settings and the sources they come from: `references/import-formats.md`.

```bash
uv run $SK/testkit-export/scripts/export_cases.py --to testrail-csv \
  -o qa/runs/<RUN_ID>/export/<RUN_ID>-testrail.csv qa/runs/<RUN_ID>/cases/*.md
uv run $SK/testkit-export/scripts/export_cases.py --to xray-csv \
  -o qa/runs/<RUN_ID>/export/<RUN_ID>-xray.csv qa/runs/<RUN_ID>/cases/*.md
```

Options: `--layout text` (TestRail single-row "Test Case (Text)" template), `--folder <path>` (section / repository root, default the ticket key), `--ticket <KEY>`, `--labels a,b` (Xray), `--bom` (when the user will open the CSV in Excel first). Export only cases the reviewer approved (`reviews/<STREAM_ID>.md` says `APPROVED`); pass just those files. Re-open the CSV with Python `csv` and check the row and column counts. Do not import into TestRail or Xray yourself: give the user the file and the wizard settings from the reference (importing writes to an outside tool).

## 5. Tell the user

Tell the user the path of each file, what it contains, and whether the visual check ran. The `export/` folder sits next to the evidence; it is not git-ignored, so the team can commit reports if they want.
