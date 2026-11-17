# Test plan — <RELEASE>

- Release / sprint: <fix version or sprint name> · Product: <project.name>
- Source of the ticket list: <JQL, fix version, or "list from the user">
- Prepared: <date> by <name / testkit> · Version: 1.0
- Status: DRAFT | APPROVED (by <name>, <date>)

## 1. Purpose and summary

<Two or three sentences: what the release contains, the highest risks, total effort, the target sign-off date.>

## 2. Scope

### In scope
| Ticket | Title | Type | Components | Spec review | Risk |
|---|---|---|---|---|---|
| PROJ-123 | ... | Story | checkout | NEEDS CLARIFICATION | high |

### Out of scope
- <ticket or area> — <reason (not in this release, covered by another team, no environment …)>

## 3. Risk assessment

<risk matrix from estimate.md>

| Ticket | Impact | Likelihood | Risk | Reason |
|---|---|---|---|---|
| PROJ-123 | high | medium | high | payment amount; spec has 3 open questions |

## 4. Test approach per area

| Area / ticket | Functional | API | Regression | Non-functional | UAT | Notes |
|---|---|---|---|---|---|---|
| Checkout (PROJ-123, PROJ-125) | yes (testkit-run) | yes | checkout, orders | performance: payment page | yes | |

- Regression scope: <areas touched by the release + core flows (login, …) + areas with recent bugs>
- Non-functional: <what, where, tool — only on environments where qa/config.yml allows it, never production>
- Automation: <existing suites to run, owner>

## 5. Environments and test data

| Environment | URL | Use | Writes allowed | Notes |
|---|---|---|---|---|
| staging | https://… | functional, regression | yes | build <…> |

- Accounts: <strategy from qa/config.yml>; roles needed: <…>
- Data: <seed data, payment sandbox, coupons, …> · Owner: <…>
- Third-party sandboxes: <…>

## 6. Entry and exit criteria

**Entry** (testing of a ticket starts when):
- the build is deployed to <env> and smoke checks pass;
- the spec review has no unanswered `high` question for that ticket (or the PO accepted the assumption);
- test data and accounts are available.

**Exit** (release is ready for sign-off when):
- 100 % of P0 and ≥ 95 % of P1 cases executed; every AC covered by at least one executed case;
- no open `blocker` or `critical` bug; `major` bugs have an agreed fix date or workaround;
- regression suite executed with no new P0 failure;
- UAT signed off (decision Accepted or Accepted with conditions).

**Suspension**: stop testing a ticket when <a blocker prevents > 30 % of its cases / the environment is down > 2 h>; resume after the fix is deployed.

## 7. Effort estimate

<estimate table, totals and assumptions from estimate.md>

## 8. Schedule

| Phase | From | To | Owner | Output |
|---|---|---|---|---|
| Spec review | | | QA | qa/specs/<KEY>/review.md |
| Test design + review | | | QA | qa/runs/<KEY>/cases |
| Execution (waves) | | | QA | qa/runs/<KEY>/results |
| Bug fix + retest | | | Dev / QA | qa/bugs |
| Regression | | | QA | |
| UAT | | | PO / business | qa/uat/<UAT_ID>/ |
| Sign-off | | | PO | acceptance minutes |

## 9. Roles and responsibilities

| Role | Name | Responsibilities |
|---|---|---|
| QA lead | | plan, triage, report, sign-off recommendation |
| Tester(s) / testkit agents | | design, execute, file bugs |
| Developer(s) | | fixes, unit/integration tests, deploys to test env |
| PO / BA | | answers questions, UAT, acceptance decision |
| DevOps | | environments, data, deploys |

## 10. Deliverables

- This plan; per-ticket plan, cases, results and report under `qa/runs/<KEY>/`
- Bug list `qa/bugs/index.md`; release test summary report
- UAT scripts and acceptance minutes under `qa/uat/<UAT_ID>/`
- Optional exports: Word/Excel under `qa/releases/<RELEASE>/export/`

## 11. Ticket runs

| Ticket | Spec review | Plan | Report | Verdict | Open bugs |
|---|---|---|---|---|---|
| PROJ-123 | [review](../../specs/PROJ-123/review.md) | [plan](../../runs/PROJ-123/plan.md) | [report](../../runs/PROJ-123/report.md) | NOT READY | 2 |
| PROJ-124 | — | not started | — | — | — |

## 12. Assumptions, dependencies, open questions

- ...
