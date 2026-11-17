# Quality audits — <RUN_ID or release> 

- Scope: <screens / routes / endpoints audited>
- Environment: <env> — <base_url> · build <version or commit if shown>
- Date: <YYYY-MM-DD> · Auditor: <agent role>
- Tools: browser-use <ver> + Chrome <ver> · axe-core 4.14.0 · Lighthouse 13.6.0 | not run · k6 <ver> | not run · ZAP 2.17.0 | not run
- Not covered: <e.g. screen reader, real devices, authenticated ZAP scan, capacity testing>

## Verdict

| Audit | Status | Findings (critical/major/minor/trivial) | Details |
|---|---|---|---|
| Accessibility | PASS / FAIL / NOT RUN | 0/2/1/0 | a11y/ |
| Performance | PASS / FAIL / NOT RUN | | perf/ |
| Visual | PASS / FAIL / NOT RUN | | visual/ |
| Load (API) | PASS / FAIL / NOT RUN (reason) | | load/ |
| Security baseline | PASS / FAIL / NOT RUN (reason) | | security/ |

## Findings → bugs

| ID | Audit | Screen / endpoint | Finding | Severity | Evidence | Bug |
|---|---|---|---|---|---|---|
| A11Y-checkout-color-contrast | a11y | /checkout | 4 nodes below 4.5:1 (WCAG 1.4.3) | major | a11y/checkout-axe.json | BUG-… or "to file" |
| PERF-checkout-mobile | perf | /checkout | LCP 4.1 s (budget 2.5 s), median of 3, slow-4g + CPU×4 | minor | perf/checkout-mobile-*.json | |

## Accepted exceptions (not filed)

| Rule / check | Reason | Where configured |
|---|---|---|

## Needs review (not confirmed)

- <axe `incomplete` items, low-confidence ZAP alerts, visual regions that may be intended>

## Raw numbers

<Per-audit tables: axe violations by impact per screen; perf metrics per profile (median); visual mismatch % per screenshot; k6 requests, p95, error rate; header check table.>
