<!--
Sources used (checked 2026-11-17):
- TestRail, "Import test cases from CSV or Excel":
  https://support.testrail.com/hc/en-us/articles/7101779988372-Import-test-cases-from-CSV-or-Excel
  (Test Case (Steps) template: a case spans several rows, standard fields + first step on the
  first row; "Sections Hierarchy" field takes a path with ">" between levels)
- TestRail, "Migration: CSV & Excel": https://support.testrail.com/hc/en-us/articles/7771173371796-Migration-CSV-Excel
- TestRail, "Migrate from Zephyr Scale" (Row Layout "Test cases use multiple rows";
  Steps(Step) / Steps(Expected Result) / Steps(Additional Info) mappings):
  https://support.testrail.com/hc/en-us/articles/11353109684372-Migrate-from-Zephyr-Scale
- TestRail, "Migration from QMetry" ("Column to detect new test cases"):
  https://support.testrail.com/hc/en-us/articles/24476164336788-Migration-from-QMetry
- Xray Cloud, "Importing Tests using Test Case Importer" (Issue Id groups rows; Summary and
  Test Type mandatory; Test Repository Folder path with "/"; list delimiter; Link fields):
  https://docs.getxray.app/display/XRAYCLOUD/Importing+Tests+using+Test+Case+Importer
- Xray Cloud, "Examples using Test Case Importer":
  https://docs.getxray.app/display/XRAYCLOUD/Examples+using+Test+Case+Importer
- Xray sample files and saved import configurations (cloud/*.csv, cloud/*.json — UTF-8, ";"
  delimiter, ";" list delimiter, field ids __xray_testId, xray_testtype, __xray_step_action,
  __xray_step_data, __xray_step_result, description, labels, xray_test_repository_folder,
  __issuelink_outward_*):
  https://github.com/Xray-App/tutorial-test-case-importer
The TestRail support site blocks automated readers; the TestRail details above come from its
articles as quoted by search results. Re-check the wizard screens if an import misbehaves.
-->

# Import CSV formats (TestRail, Xray Cloud)

`scripts/export_cases.py` writes both files from `qa/runs/<RUN_ID>/cases/*.md`. Neither tool needs exact header names: both import wizards let you map each CSV column to a field. The headers below are chosen so the mapping is obvious. Columns the target project does not need can be set to "do not map / ignore".

Encoding is UTF-8 (Vietnamese text survives). `--bom` adds a byte-order mark so Excel opens the file with the right encoding; both importers accept it, but without `--bom` the first header name is cleaner in the mapping screen.

## TestRail (`--to testrail-csv`)

Comma-delimited. Two layouts:

### `--layout steps` (default) — template "Test Case (Steps)"

One case spans several rows. The first row holds every case field plus step 1; each later row has only the next step. Expected results of a testkit case are a list for the whole case, so they go on the **last** step row.

| Column | TestRail field | Value |
|---|---|---|
| Section Hierarchy | Section Hierarchy (Sections Hierarchy) | `<folder> > <STREAM_ID> — <stream title>`; `>` inside titles is replaced by `-` |
| Title | Title | case title (first row only — this is the column that detects a new case) |
| Test ID | (custom field, or ignore) | `TC-S1-001` |
| Type | Type | `Functional`; `Security` for permission, `Usability` for ui, `Regression`, `Accessibility` |
| Priority | Priority | P0 → `Critical`, P1 → `High`, P2 → `Medium` |
| References | References | ticket key (`PROJ-123`) |
| Requirement | (custom field, or ignore) | `AC-1` |
| Preconditions | Preconditions | preconditions, then `Test data: …` and `Depends on: …` lines |
| Steps (Step) | Steps (Step) | one step per row, numbering removed |
| Steps (Expected Result) | Steps (Expected Result) | `- …` bullet lines, on the last step row |

Wizard settings: Administration / Test Cases → **Import from CSV**; encoding UTF-8, delimiter `,`, header row 1, template **Test Case (Steps)**; step 2: Row Layout **Test cases use multiple rows**, **Column to detect new test cases = Title**, tick "ignore empty rows"; map columns as above; step 3: map Type and Priority values if the project renamed them.

### `--layout text` — template "Test Case (Text)"

One row per case; `Steps` is a numbered list and `Expected Result` a bullet list in one cell each (quoted multi-line cells). Row Layout **Test cases use a single row**. Use this when the project uses the Text template or when you import into a TestRail version without separated steps.

## Xray Cloud (`--to xray-csv`)

Semicolon-delimited, like Xray's own samples. Rows that share an `Issue Id` are one test; the first row holds the test fields and step 1, the next rows only the next step. `Issue key` stays empty (new tests).

| Column | Xray / Jira field (field id in a saved config) | Value |
|---|---|---|
| Issue Id | Issue Id (`__xray_testId`) | 1, 2, 3 … per case |
| Issue key | Issue key (`__issue_key`) | empty — fill it to update existing tests instead |
| Test type | Test Type (`xray_testtype`) | `Manual` (must exist in the project) |
| Test Summary | Summary (`summary`) | `TC-S1-001 <title>` |
| Test Priority | Priority (`__priority_name`) | P0 → `Highest`, P1 → `High`, P2 → `Medium` |
| Labels | Labels (`labels`) | `testkit;TC-S1-001;PROJ-123-S1` (list delimiter `;`, quoted) |
| Description | Description (`description`) | preconditions, depends on, requirement, source file |
| Action | Action (`__xray_step_action`) | one step per row |
| Data | Data (`__xray_step_data`) | test data on step 1 |
| Result | Expected Result (`__xray_step_result`) | `- …` bullets on the last step row |
| Test Repo | Test Repository Folder (`xray_test_repository_folder`) | `<folder>/<STREAM_ID> <stream title>`; `/` in titles becomes `-` |
| Tests | Link "tests" (outward, `__issuelink_outward_<id>`) | ticket key, so the test covers the story |

Wizard settings: Xray → **Test Case Importer** → CSV; encoding UTF-8, delimiter `;`, list delimiter `;`; tick "create test repository folders"; choose the Jira project; map the columns as above (step fields are in the group "Xray Test Step Fields"). Xray limits an import to 2000 issue links, not counting each test's first link. Save the configuration in the importer so the next import maps itself.

Xray Server/Data Center uses a slightly different importer format; this file targets Xray Cloud.

## Checks before handing the file over

- Re-open the CSV with Python `csv` (delimiter `,` or `;`) and confirm every row has the header's column count and the case count matches the run.
- A cell starting with `=`, `+` or `@` makes the script print a warning: spreadsheet apps would read it as a formula. Rephrase the case text if the file will be opened in Excel before import.
- Placeholders such as `{{member.email}}` are kept as written; tell the user they refer to accounts the testkit executor creates.
