---
name: testkit-knowledge
description: Project knowledge and decision memory for testkit — builds and refreshes qa/knowledge/project-map.md (modules, screens, API endpoints, roles, data states, integrations, environments, flags, existing tests, Vietnamese-English glossary, risky areas), records product and test decisions as D-… files, keeps a registry of project documents (Word, PDF, Confluence, Figma), and mirrors all of it into a Graphiti knowledge graph for recall. Files stay the source of truth; the graph is optional. Use to "learn the project", before planning or judging expected behaviour (recall), when a PO/user answers a question or a bug is ruled won't-fix (remember), when specs change (docs), or when the user says "tìm hiểu dự án", "học dự án", "ghi nhớ quyết định", "nhớ lại", "quyết định trước đây là gì", "kiến thức dự án", "knowledge graph", "project map".
argument-hint: "learn [--since <git ref>] | docs [paths/URLs] | remember \"<decision>\" | recall \"<question>\" | status"
---

# testkit knowledge

Long-lived project knowledge for every testkit role. Files in `qa/knowledge/` are the source of truth (git-tracked, reviewable); a Graphiti graph, when available, is a searchable mirror. Everything works without the graph.

```
qa/knowledge/project-map.md                 what the product is (learn)
qa/knowledge/decisions/D-<YYYYMMDD>-<NN>-<slug>.md + README.md   one decision per file + index (remember)
qa/knowledge/sources.yml                    document registry (docs)
qa/knowledge/sources/<id>.md                converted documents
qa/knowledge/.pending/  .graph-state.json   queued episodes / what this machine sent (git-ignored)
```

## 0. Prepare

1. Read `qa/config.yml`. If it is missing, tell the user to run `testkit init` and stop. If `knowledge.enabled: false`, say so and stop.
2. Commands run from the project root with:
   `SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)   # the skills folder testkit installed into`
   `KG="uv run $SK/testkit-knowledge/scripts/kg.py"`
3. `$KG status` shows: files present, the graph URL (or "unreachable"), consent, pending and failed episodes. Without a graph, keep going: write the files and let `kg.py` queue the episodes.

### Consent before the first ingestion

Graphiti sends every episode to its LLM and embedding provider. If `kg.py` prints `QUEUED, NOT SENT … consent`, ask the user once, naming the provider (`testkit graph status` in the terminal shows it for the local stack): *"testkit will send project knowledge (decisions, project map, documents) to <provider> through the graph at <url>. OK?"*
- Yes → set `knowledge.graphiti.consent: granted` in `qa/config.yml`, then `$KG flush`.
- No → set `knowledge.graphiti.consent: denied`; knowledge stays in files only.
A local stack with an Ollama LLM needs no consent.

## learn — build or refresh the project map

1. Facts first: `uv run --no-project $SK/testkit-knowledge/scripts/project_scan.py --out qa/.cache/knowledge-scan.json` (add `--since <ref>` for an incremental refresh; default ref = `scanned_ref` in the map's frontmatter). It lists stacks, routes, OpenAPI endpoints, role/permission code, data models and status enums, env var **names**, feature flags, integrations, i18n files, CI jobs, test folders and frameworks, agent instruction files and skills folders.
2. Read, in this order, and reuse instead of copying: existing `qa/knowledge/` files; `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.github/copilot-instructions.md`, `.cursor/rules/`; `README*` and `docs.paths`; other skills in the skills folders (not testkit's own, flagged `"testkit": true`); then the code at the `file:line` locations the scan found. Link to a source rather than repeating long passages.
3. Write `qa/knowledge/project-map.md` from `assets/project-map-template.md`: keep its headings (the graph keys episodes by heading), write in `project.language`, cite `file:line` or document paths in every section, and mark unknowns as `unknown — ask <PO/dev>` instead of guessing. `references/project-map-guide.md` says what goes in each section. On refresh, edit only sections the changed files touch and update `updated` and `scanned_ref`.
4. Ingest the sections (unchanged sections are skipped automatically):
   `$KG add --key map --name "Project map" --file qa/knowledge/project-map.md --chunk --source-description "testkit project map qa/knowledge/project-map.md" --reference-time <today>`
5. Tell the user: sections written, open unknowns, and that the map is ready for review in git.

## docs — document registry

1. `uv run $SK/testkit-knowledge/scripts/docs_registry.py sync` scans `docs.paths`, hashes every `.docx`, `.pdf`, `.md`, `.txt` and OpenAPI file, converts Word (pandoc) and PDF (`testkit-spec-review` converter) into `qa/knowledge/sources/<id>.md`, and marks entries `current | changed | removed`. Extra files: `--path <file|dir>`. Pages: `--url <confluence|figma|other URL>` registers them; fetch the page with your Atlassian/Figma tools, save the text as `qa/knowledge/sources/<id>.md` (path printed), run `sync` again. Scanned PDFs: follow the `pdf` skill.
2. `... docs_registry.py ingest` sends new/changed documents, one episode per heading section, dated with the file date.
3. Documents marked `removed` that are still in the graph: confirm with the user, then `docs_registry.py prune --yes`.
4. Report: new, changed, removed documents, conversion errors, and which decisions or project-map sections a changed document may affect (search `qa/knowledge/` for its id and topics).

## remember — record a decision

Use for: answers to open questions, accepted product behaviour, test-scope choices, environment and test-data conventions, known flaky areas, won't-fix rulings. One decision per call.

1. Recall first (`$KG search "<topic>"`, `decisions.py list --area <area>`). If an accepted decision on the same point exists, the new one supersedes it.
2. Write it:
   ```
   uv run $SK/testkit-knowledge/scripts/decisions.py new --title "<one-line rule>" --area <feature> \
     --tags <a,b> --source "<who decided, where, date: PO answer in PROJ-123 comment>" \
     --related <PROJ-123,TC-S2-004,BUG-…> [--supersedes D-…] [--date YYYY-MM-DD] \
     --context "<why it came up>" --decision "<the rule, testable>" --consequence "<what tests must check>"
   ```
   Title, context, decision and consequence in `project.language`. The source names a role and a place, never personal contact data. `--status rejected` records a proposal that was turned down.
3. The script writes the file, marks the superseded one, rebuilds `decisions/README.md` and sends both to the graph (or queues them). Tell the user the new id.

## recall — answer from project knowledge

1. `$KG search "<question>" --max 10` prints graph facts (with validity dates and the episode keys they came from) **and** matching lines in `qa/knowledge/` files. Add your own `rg -n -i "<terms>" qa/knowledge/` (or `grep -rni`) for exact ids and Vietnamese/English synonyms from the glossary.
2. Open every decision file you rely on. Only `status: accepted` counts; for a superseded one follow `superseded_by`. Files win over the graph when they disagree (the graph may be behind: `NOTE: … pending`).
3. Answer with citations: `D-20261117-01`, `qa/knowledge/project-map.md § Roles`, `qa/knowledge/sources/<id>.md`. Say plainly when: the graph is unavailable (files only), a fact is marked `NO LONGER VALID`, the project map's `updated` date is older than the last changes in the area, or nothing was found (then it is an open question, not a rule).

## Pipeline hooks (used by other testkit skills)

- **Run summary** (test-lead, report step):
  `$KG add --key run:<RUN_ID> --name "Run <RUN_ID> summary" --reference-time <today> --source-description "testkit run summary qa/runs/<RUN_ID>/report.md" --file -` with a short body: ticket and title, environment, verdict, streams (id, area, pass/fail/blocked counts), bug ids with severity and title, decisions used. No accounts, passwords, tokens or customer data; `kg.py` masks e-mails and phone numbers anyway.
- **Bug status change** (test-lead / testkit-verify): `$KG add --key bug:<BUG_ID>#<status> --name "<BUG_ID> <status>: <title>" --text "<BUG_ID> (<severity>, <area>) is now <status> on <date>: <one line why>" --source-description "testkit bug qa/bugs/<BUG_ID>.md" --reference-time <date>`.
- **Answered questions and won't-fix rulings** → `remember`.

## status

`$KG status`, `decisions.py list`, `docs_registry.py list`, and in the terminal `testkit graph status`. Episodes listed as `failed` were sent but never stored (LLM/API error): check `testkit graph logs`, fix, then `$KG flush --retry-failed`. `references/graph.md` covers setup, providers, what works without API keys, and troubleshooting.

## Rules

- Never ingest secrets, credentials, tokens, connection strings, `.env` values or personal data. `kg.py` redacts obvious secrets and masks e-mails/phones, but you must not paste them in the first place. Env files: names only.
- Respect `knowledge.enabled: false` (do nothing) and `knowledge.graphiti.enabled: false` or `consent: denied` (files only).
- Ask before the first ingestion into a graph whose LLM provider is a cloud API (see Consent).
- Files first, graph second: write or update the file, then ingest it. Never keep knowledge only in the graph.
- Decisions are append-only history: supersede or reject, do not delete. Fix typos in place and re-run `decisions.py ingest <id>`.
- Talk to the graph only through `kg.py` (it applies the project's `group_id`, safety filters and the pending queue). Other agents' MCP graph tools may read, but must pass the same `group_id`.
