# Writing the project map

The map is for testers and agents who must plan tests in this product without reading the whole repo. Facts with sources beat prose. Aim for 150–400 lines; link to longer material.

## Inputs and how to use them

| Input | Use |
|---|---|
| `project_scan.py` JSON | Starting facts. Verify a sample of routes/roles in code before writing them down; regex scans miss things and catch false positives. |
| `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, copilot/cursor rules | Team conventions, commands, architecture notes. Link them in *Sources*; copy only what testers need. |
| `README*`, `docs.paths`, `qa/knowledge/sources/*.md` | Product behaviour, business rules, glossary. Cite as `<file> § <heading>`. |
| Other skills (`.claude/skills/*`, `.agents/skills/*`, not testkit's) | How the team deploys, seeds data, runs things. Mention under *Existing tests and CI* or *Environments*. |
| `qa/config.yml` | Environments, roles, accounts strategy, tracker. The map does not repeat secrets or account data. |
| `qa/knowledge/decisions/` | Accepted decisions override docs; mention the `D-…` id next to the rule it changes. |
| `qa/specs/*/review.md`, `qa/runs/*/report.md`, `qa/bugs/index.md` | Risky areas (many bugs, reopened bugs, open questions). |

## Section notes

- **Product overview**: users, main journeys, platforms (web, mobile, admin back-office).
- **Modules and features**: one row per module the tester would name; link code folder and main doc.
- **Screens and routes**: UI routes from the router or file-system pages; include admin screens. Note which role sees them.
- **API endpoints**: prefer the OpenAPI file; otherwise routes from the scan joined with router mount prefixes (`router mount` rows). Do not list hundreds: group, and list the ones with business rules, permissions or money.
- **Roles and permissions**: from role constants, guards/middleware and the docs. Note mismatches between docs and code as open questions (do not choose a winner).
- **Data entities and states**: models plus status enums; draw transitions as `PENDING → PAID → SHIPPED`, `PENDING → CANCELLED (≤ 30 min, D-…)`.
- **Integrations**: payment, e-mail, SMS/OTP, storage, analytics, auth providers. Sandbox/test mode and env var **names**.
- **Environments**: from `qa/config.yml` plus deploy docs; reset schedules and data rules.
- **Feature flags**: flag name, what it changes, default per environment if known.
- **Existing tests and CI**: frameworks, folders, how to run locally, CI jobs and which ones block merges; what is not covered.
- **Glossary**: Vietnamese UI/business terms and the English names used in code (e.g. *Hủy đơn* ↔ `cancelOrder`). Recall uses it to search both languages.
- **Risky areas**: money, permissions, state machines, time zones, concurrency, integrations, areas with many bugs, code without tests.
- **Sources**: every file and URL used, so a refresh knows what to re-read.

## Refresh (`--since`)

1. `project_scan.py --since <scanned_ref>` lists changed files and scans only them for routes/roles/entities/flags.
2. Map each changed file to sections (route file → *Screens/API*, model/migration → *Data entities*, guard → *Roles*, CI file → *Existing tests and CI*).
3. Edit only those sections; keep the rest byte-identical so their graph episodes stay unchanged.
4. Update `updated` and `scanned_ref`, then ingest (`kg.py add --key map … --chunk`): only changed sections are re-sent.
