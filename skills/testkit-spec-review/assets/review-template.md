# Spec review — <SPEC_ID>: <title>

- Ticket: <key + link, or "none">
- Reviewed: <date> · Code at: <branch/commit if read>
- Readiness: <READY | NEEDS CLARIFICATION | NOT READY> — <one sentence why>
- Counts: <n> AC · <n> ambiguities · <n> contradictions · <n> missing cases · <n> questions (<n> high)

## Sources

| # | Source | Type | Version / date | Converted to |
|---|---|---|---|---|
| 1 | PROJ-123 (Jira) | ticket | updated 2026-11-15 | — |
| 2 | Đặc tả thanh toán v1.3.docx | Word | v1.3 | sources/dac-ta-thanh-toan-v1.3.md |
| 3 | Checkout — Figma | design | frame "Checkout / Coupon" | sources/figma/checkout-coupon.png |

Not reviewed: <sources you could not read and why, e.g. "Figma: no Figma tools in this session">

## Acceptance criteria

| ID | Criterion | Source | Testable | Notes |
|---|---|---|---|---|
| AC-1 | ... | <file> § <heading> | yes / partly / no | T-1 |

## Ambiguities

| ID | Text (quoted) | Source | Possible readings | Question |
|---|---|---|---|---|
| A-1 | "..." | ... | 1) ... 2) ... | Q-3 |

## Contradictions

| ID | Between | Says | Versus | Question |
|---|---|---|---|---|
| C-1 | docs vs design | "..." (<source>) | "..." (<source>) | Q-1 |

## Missing cases

| ID | Area | What is not specified | Assumption until answered | Question |
|---|---|---|---|---|
| M-1 | errors | ... | ... | Q-2 |

## Testability issues

| ID | AC | Problem | What would make it testable |
|---|---|---|---|
| T-1 | AC-1 | ... | ... |

## Risks

| ID | Risk | Impact | Likelihood | Test focus |
|---|---|---|---|---|
| R-1 | ... | high | medium | ... |

## Design check

<Per screen: labels, messages, states, formats compared with the docs; or "Skipped: no Figma tools available — ask the designer for exported frames to include them.">

## Code notes

- `<file>:<line>` — <behaviour relied on or that differs from the docs>

## Questions for PO / dev

Ranked by impact. Answers go in the last column; re-run the review to fold them in.

| ID | Impact | For | Question | Why it matters | Refs | Answer |
|---|---|---|---|---|---|---|
| Q-1 | high | PO | ... ? (A or B) | blocks AC-2 test design | C-1, AC-2 | |

## History

- <date> review created
