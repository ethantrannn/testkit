---
name: testkit-uat
description: Prepare and close user acceptance testing (UAT) — turns acceptance criteria into UAT scripts in business language (one scenario per business flow, no technical selectors) as an Excel sheet the business fills in (Scenario ID, Business flow, Preconditions, Steps, Expected result, Pass/Fail, Comment, Tester, Date), then reads the filled sheet and drafts the acceptance sign-off minutes (biên bản nghiệm thu) in Word with scope, results, open defects, decision and signature blocks. Use when the user asks for UAT scripts, acceptance testing, sign-off, "kịch bản UAT", "kiểm thử chấp nhận", "nghiệm thu", "biên bản nghiệm thu".
argument-hint: "<ticket key | release | RUN_ID ...> [--id <UAT_ID>] [scripts | minutes <filled.xlsx>]"
---

# testkit UAT

Two steps, usually days apart:

1. **scripts** — write UAT scenarios and the Excel sheet the business users fill in.
2. **minutes** — read the filled sheet and draft the acceptance minutes in Word.

Outputs go to `qa/uat/<UAT_ID>/`. `UAT_ID` = `--id`, else the ticket key (`PROJ-123`) or the release name (`2026.11`). Commands run from the project root with:
`SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)   # the skills folder testkit installed into`

Read `qa/config.yml` first (`project.name`, `project.language`, `environments`). If it is missing, tell the user to run `testkit init` and stop. The workbook and the minutes are rendered by the `testkit-export` scripts; read that skill's model formats (`references/xlsx-model.md` and section 2 of its `SKILL.md`) before building the models.

## 1. Scripts

### Sources of acceptance criteria (first found wins, per ticket)

1. `qa/specs/<KEY>/review.md` — AC list with answers folded in (from `testkit-spec-review`).
2. `qa/runs/<KEY>/plan.md` — *Acceptance criteria*.
3. The ticket itself (Atlassian tools if available, else ask the user to paste it).

For a release, take every in-scope ticket from `qa/releases/<RELEASE>/test-plan.md` that the plan marks for UAT.

### Write the scenarios

- **One scenario per business flow**, not per AC: a flow is what a business user does end to end to reach a goal ("Khách hàng dùng mã giảm giá khi thanh toán"). A scenario may cover several ACs; every in-scope AC is covered by at least one scenario.
- **Business language only**: screen names and button labels as the user sees them, business data ("khách hàng có đơn 1.000.000 ₫"). No CSS/XPath selectors, URL paths, API names, HTTP codes, database terms or test-account placeholders like `{{member}}`. Say "tài khoản khách hàng do QA cung cấp" instead.
- **Steps**: 3–8 numbered actions. **Expected result**: what the user can see or check (amount, message, status, email received), one bullet per check. Where the spec does not give the exact text, describe it ("thông báo áp mã thành công").
- **Preconditions**: the business state needed (account type, data in place, period/time), and who prepares it.
- Include the important negative flows a business user cares about (expired coupon, no permission), not technical edge cases — those belong to `testkit-run`.
- IDs: `UAT-01`, `UAT-02` … never reused. Keep the IDs when you update the scripts.

Write `qa/uat/<UAT_ID>/uat-scripts.md` (the source of truth: header with project, scope, environment, period; a traceability table `AC | Scenarios`; one section per scenario with the fields above), in `project.language`.

### Build the Excel sheet

Copy `assets/uat-workbook.example.json` to `qa/uat/<UAT_ID>/uat.xlsx.json` and replace the content, keeping the structure:

- sheet `Hướng dẫn` / `Instructions`: title, meta (project, scope, environment with URL from `qa/config.yml`, period, QA contact), a table explaining which columns to fill, with one example value each;
- sheet `UAT`: columns `Scenario ID | Business flow | Preconditions | Steps | Expected result | Result | Comment | Tester | Date` (headers in `project.language`, Scenario ID kept as is), `Result` with `"choices": "uat"` (Pass/Fail), the last four columns empty;
- sheet `Defects`: `Defect ID | Scenario ID | Description | Severity | Status | Reported by | Date`, `blank_rows: 20`;
- sheet `Traceability`: `AC | Scenario ID`.

Keep the `UAT` sheet name and the column order: `read_uat_results.py` reads by position. Render:

```bash
uv run $SK/testkit-export/scripts/build_xlsx.py qa/uat/<UAT_ID>/uat.xlsx.json qa/uat/<UAT_ID>/<UAT_ID>-uat.xlsx
```

It must end with `check: no formulas` and `check: OK`. Look at it (`qlmanage -t -s 1400 -o qa/uat/<UAT_ID> <file>.xlsx` on macOS shows the first sheet; open the image). Tell the user the path, the number of scenarios and the ACs covered, and that testers fill only Result, Comment, Tester, Date and the Defects sheet.

## 2. Minutes (biên bản nghiệm thu)

Input: the filled workbook (ask the user for it; save it as `qa/uat/<UAT_ID>/<UAT_ID>-uat-filled.xlsx`, never overwrite the blank one).

```bash
uv run $SK/testkit-uat/scripts/read_uat_results.py qa/uat/<UAT_ID>/<UAT_ID>-uat-filled.xlsx \
  --json qa/uat/<UAT_ID>/results.json > qa/uat/<UAT_ID>/results.md
```

It prints totals, failed and not-run scenarios with comments, and the defects. Also read `qa/bugs/` for open bugs of the tickets in scope (`ticket` field) — open `blocker`/`critical`/`major` bugs go into the open defects table even if UAT did not hit them.

Ask the user (one message) for what the sheet does not hold: participants (name, unit, role), the location/meeting, the build/version, and **the decision**. Never decide acceptance yourself; you may propose one: `Accepted` when all scenarios passed and no open blocker/critical/major defect; `Accepted with conditions` when the failures have agreed fixes and dates; `Rejected` when a core flow fails. If the user does not answer, leave all three boxes unticked (`☐`).

Copy `assets/acceptance-minutes.example.json` to `qa/uat/<UAT_ID>/minutes.json` and fill it:

1. Title `BIÊN BẢN NGHIỆM THU` (en: `USER ACCEPTANCE SIGN-OFF`), subtitle with scope; `meta`: project, scope, version/build, environment, UAT period, date of the minutes, location.
2. Participants table.
3. Scope in / out (ACs or flows).
4. Summary of results: totals table, then `Scenario ID | Business flow | Result | Comment` with `PASS`/`FAIL` in upper case so the cells are coloured; not-run scenarios say so in the comment.
5. Open defects: `ID | Description | Severity | Status | Handling / due date`.
6. Decision: three paragraphs `☐/☒ Chấp nhận (Accepted)`, `☐/☒ Chấp nhận có điều kiện (Accepted with conditions)`, `☐/☒ Không chấp nhận (Rejected)`; for conditions, a numbered list with owner and date.
7. Signatures: one table, one column per signing party, cell text `(Ký, ghi rõ họ tên)` + five empty lines + name + `Ngày: ....../....../<year>`. If the user needs the formal national header for a contract (`CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM / Độc lập - Tự do - Hạnh phúc`), add it as the first paragraphs and ask for the contract number.

Render, validate and look at it:

```bash
uv run $SK/testkit-export/scripts/build_docx_report.py qa/uat/<UAT_ID>/minutes.json \
  qa/uat/<UAT_ID>/<UAT_ID>-bien-ban-nghiem-thu.docx
uv run --with lxml --with defusedxml python $SK/docx/scripts/office/validate.py qa/uat/<UAT_ID>/<UAT_ID>-bien-ban-nghiem-thu.docx
```

Validation must print `All validations PASSED!`. Check page one with `qlmanage -t -s 1400 -o qa/uat/<UAT_ID> <file>.docx` (macOS) and the rest with `pandoc -t plain <file>.docx`. Use the English file name `<UAT_ID>-acceptance-minutes.docx` when `project.language` is not `vi`.

Tell the user: totals, failed scenarios, open defects, the decision as recorded (or that it is blank), and both paths. The minutes are a draft until people sign; do not send them anywhere yourself.

## Rules

- UAT is run by business users; this skill does not execute the scenarios in a browser. If the user wants a dry run first, run `testkit-run` on the ticket instead.
- Defects from the sheet that are real product bugs: offer to file them in `qa/bugs/` following the `bug-reporting` skill (ID `BUG-<UAT_ID>-UAT-<NN>`), and in Jira only after the user agrees.
- Do not put passwords or personal data of real customers into the sheet or the minutes.
