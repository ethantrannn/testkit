---
name: testkit-automate
description: Turn approved and executed testkit cases into a maintained Playwright Test (TypeScript) regression suite in qa/automation — one spec per stream, TC-id test titles, @smoke for P0, known bugs as test.fail, storageState auth from env-var accounts, per-run test data, coverage.md traceability, CI templates for GitHub Actions and GitLab. Use when the user wants regression/e2e automation from a run, "automate these cases", "generate Playwright tests", "smoke suite", "add to CI", "tự động hoá test case", "viết script Playwright", "chạy regression", or after testkit-run when cases passed and should stay protected.
argument-hint: "<RUN_ID> [--streams S1,S2] [--env <name>] [--ci github|gitlab]"
---

# testkit automate (Playwright)

Manual runs prove a ticket once; this skill keeps it proven. You turn executed cases into Playwright tests, run them against a configured environment until they are green for the right reason, and keep a traceability file that says which case is automated where.

Node.js is required here because Playwright is Node-native: **Node 20 or newer** (CI templates use 24 LTS) with npm. Everything else follows the usual testkit rules.

```bash
SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)   # the skills folder testkit installed into
```

Read `references/spec-patterns.md` before writing specs. Read `test-case-standard` if the case format is unfamiliar.

## 1. Inputs and what is eligible

- `RUN_ID`, optional stream filter, environment (default: `automation.environment` in `qa/config.yml`, else `default_environment`).
- Per stream read `cases/<S>.md`, `reviews/<S>.md` (must say `APPROVED`), `results/<S>.md`, and the bug files the results link.

| Manual result | Automate? |
|---|---|
| `PASS` | yes, as a normal test |
| `FAIL` with a bug in status `open`/`reopened`/`fixed` | yes, with the **case's** expectation, as `test.fail` + `bug` annotation (see spec-patterns) |
| `FAIL` with a `verified` bug | yes, as a normal test (it is a regression test now) |
| `FAIL` without a bug, `BLOCKED`, `SKIPPED`, not executed | no: `not-eligible` in coverage; tell the user why |
| needs human judgement, real email/SMS/OTP without an API, hardware, captcha, third-party payment page | no: `manual-only` with the reason |

Never automate a case whose review is not `APPROVED`: the suite would freeze an unreviewed expectation.

## 2. Scaffold `qa/automation/` (first time only)

```bash
mkdir -p qa/automation/tests/support
cp $SK/testkit-automate/assets/package.json $SK/testkit-automate/assets/playwright.config.ts qa/automation/
cp $SK/testkit-automate/assets/tests/auth.setup.ts qa/automation/tests/
cp $SK/testkit-automate/assets/tests/support/*.ts qa/automation/tests/support/
cp $SK/testkit-automate/assets/gitignore.txt qa/automation/.gitignore
```

| File | Role |
|---|---|
| `package.json` | pinned `@playwright/test` and `@types/node`; scripts `test`, `test:smoke`, `report` |
| `playwright.config.ts` | `baseURL` from `TESTKIT_BASE_URL` (fails fast if unset), projects `setup` → `chromium` + `mobile` (Pixel 7 viewport, same Chromium), trace and screenshot kept on failure, reporters list + JUnit (`reports/junit.xml`) + HTML (`reports/html`) |
| `tests/auth.setup.ts` | signs in once per role, saves `.auth/<role>.json` (storageState). **Edit `ROLES` and the sign-in steps** to the product's real sign-in screen |
| `tests/support/accounts.ts` | `credentials(role)` from `TESTKIT_E2E_<ROLE>_EMAIL/_PASSWORD/_NAME`, `authFile(role)`, `SIGNED_OUT` |
| `tests/support/data.ts` | `unique(label, testInfo)`, `uniqueEmail(role, testInfo)` for per-run test data |
| `.gitignore` | `node_modules/`, `.auth/`, `test-results/`, `reports/` (they hold sessions and typed passwords) |

Commit `package.json`, `package-lock.json`, the config, `tests/` and `coverage.md`. When upgrading Playwright, change the version in `package.json`, the GitLab image tag, then `npm install` and re-run the whole suite.

Accounts for local runs: add dedicated automation accounts to the git-ignored `qa/accounts.local.json` under `"automation": {"member": {"email": "...", "password": "...", "name": "..."}}`. Without that entry `run_suite.py` falls back to the newest executor account of that role from `runs`. Never write credentials into specs, config or CI files.

## 3. Generate the specs

For each eligible stream write `qa/automation/tests/<RUN_ID>/<STREAM_ID>-<feature-slug>.spec.ts` following `references/spec-patterns.md`:

- First line `// testkit-run: <RUN_ID>`; one `test.describe('<RUN_ID> <STREAM_ID> — <stream title>')`.
- One test per case, title `TC-<S>-<NNN> <case title>`; P0 gets `{ tag: '@smoke' }`.
- Each step becomes an action, each expected bullet becomes at least one web-first assertion with the exact text/URL/state from the case. Do not invent expectations the case does not have, do not drop ones it has.
- Locators: `getByRole` → `getByLabel` → `getByTestId` → text; no XPath, no generated CSS classes, no `waitForTimeout`.
- Signed-in tests use `test.use({ storageState: authFile('<role>') })`; sign-in/sign-up cases use `SIGNED_OUT`.
- Data the test creates is named with `unique(...)`; assertions target that record only.
- Page objects (`tests/pages/<screen>.ts`) only when 3+ spec files share a screen.
- If a selector can only be written fragile, keep it and list a testability request (e.g. "add `data-testid` to the account menu").

Before running, explore unclear screens in a browser (the `browser-testing` skill, session `<RUN_ID>-automate`) to read real labels and roles from the accessibility tree instead of guessing.

## 4. Run until green for the right reason

```bash
uv run $SK/testkit-automate/scripts/run_suite.py --install            # first time: npm ci/install + Chromium, then all tests
uv run $SK/testkit-automate/scripts/run_suite.py -- tests/<RUN_ID>/    # only the new specs
uv run $SK/testkit-automate/scripts/run_suite.py -- --grep @smoke      # smoke suite
uv run $SK/testkit-automate/scripts/run_suite.py --env staging -- --project chromium
```

`run_suite.py` reads `qa/config.yml`, sets `TESTKIT_BASE_URL` from the environment's `base_url`, fills `TESTKIT_E2E_<ROLE>_*` from `qa/accounts.local.json` (never prints them), refuses environments not in the config or with `allow_write: false`, and runs `npx playwright test` inside `qa/automation`. Equivalent by hand: `cd qa/automation && TESTKIT_BASE_URL=<url> TESTKIT_E2E_MEMBER_EMAIL=… npx playwright test --grep @smoke`.

For every failing test, read `test-results/<test>/error-context.md`, open `test-failed-1.png` and look at it, and if needed the trace (`npx playwright show-trace <trace.zip>`). Then decide:

| Cause | Action |
|---|---|
| Test problem: wrong locator, missing wait, wrong data, bad precondition, auth setup | **Fix the test**, re-run. |
| Product differs from the case's expected result | **Do not change the expectation.** Reproduce it manually once (or confirm the manual result was also FAIL). File a bug following `bug-reporting` (evidence: the screenshot and trace path), then mark the test `test.fail` with that bug id. |
| Case itself is wrong or ambiguous (docs changed) | Stop for that case. Report it as a case problem for the writer; leave it `pending`. |
| Environment down or flaky | Re-run once; if still failing, report it, do not mark anything. |

**Never weaken an assertion to make a test pass**: no looser regex, no removed assertion, no `toBeVisible` instead of `toHaveText`, no bigger timeout beyond what the case allows, no `test.skip`/`fixme` to hide a red test, no `retries` to absorb a real failure. A test that passes only on retry is flaky: find the cause.

Stop when every generated test is green (passing, or failing as expected under `test.fail`), or when the remaining reds are real bugs you filed. Run the full suite once on both projects (`chromium`, `mobile`) before you finish; a case that only fails on `mobile` is a real result (responsive bug or a test that needs a viewport-specific step).

## 5. Coverage file

```bash
python3 $SK/testkit-automate/scripts/coverage.py --run <RUN_ID> \
  --manual "TC-S1-004=focus outline needs visual judgement" --check
```

It writes `qa/automation/coverage.md`: one row per case of the selected runs with `Run | TC | Title | Priority | Manual result | Status | Spec | Reason / notes`, where Spec is `tests/<file>.spec.ts:<line>` and Status is `automated` (with `known bug BUG-… (test.fail)` when expected to fail), `manual-only` (reason required, kept on later runs), `pending` or `not-eligible`. With no `--run` it covers every run already referenced by specs or by the file. `--check` fails when a spec title names a TC id that does not exist in the run. Re-run it after every spec change.

## 6. CI (when asked, or `automation.ci` is set)

- GitHub Actions: copy `assets/github-actions.yml` to `.github/workflows/e2e.yml`.
- GitLab CI: merge `assets/gitlab-ci.yml` into `.gitlab-ci.yml` (or `include:` it).

Both run `npm ci`, cache npm (and the browser download on GitHub), run the smoke suite on pull/merge requests and the full suite on a nightly schedule, and upload `reports/` + `test-results/` (HTML report, JUnit, traces) as artifacts for 14 days. Actions are pinned to commit SHAs with the version in a comment; the GitLab image `mcr.microsoft.com/playwright:v<version>-noble` must match the `@playwright/test` version.

Tell the user what to configure, without values: variable `TESTKIT_BASE_URL` (a non-production environment from `qa/config.yml`), secrets `TESTKIT_E2E_<ROLE>_EMAIL/_PASSWORD` (+ `_NAME` if used) per role in `auth.setup.ts`, and the GitLab pipeline schedule. Add one `env:`/variable line per extra variable the suite reads. Ask before committing CI files or pushing.

## 7. Report back

- Specs written (paths), tests per stream, smoke count.
- Last run: passed / expected-to-fail (known bugs) / failed, per project; HTML report path `qa/automation/reports/html/index.html`.
- Bugs filed while automating (ID, severity, title) and case problems for the writer.
- Coverage summary line from `coverage.md`, manual-only cases with reasons.
- Testability requests (missing labels/test ids) and anything left `pending`.

## Safety

- Only environments listed in `qa/config.yml`; never production, never one with `allow_write: false` (the suite signs in and creates data). Do not add load, brute-force or security-scan steps to the suite.
- Credentials only through environment variables / CI secrets. Traces, screenshots and the HTML report contain typed values including passwords: keep them out of git and out of public issues.
- Ask before committing, pushing, or adding CI secrets on the user's behalf.
