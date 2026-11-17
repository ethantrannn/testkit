---
name: api-testing
description: How testkit designs and runs REST and GraphQL API test cases with Hurl — `Type: api` cases (method, endpoint, auth role, request, expected status/body/headers/schema), one .hurl file per case under qa/runs/<RUN_ID>/api/<STREAM_ID>/, run with a safety-checked runner that passes accounts and tokens as secrets and saves JSON/JUnit reports as evidence. Covers login and token capture, permission matrix and IDOR, validation and boundaries, error format, pagination, idempotency, uploads, GraphQL, schema checks, endpoint discovery from OpenAPI/routes/network logs, and running existing Postman (Newman) or Bruno collections. Use when a ticket changes an API or backend behaviour, when the user says "test API", "kiểm thử API", "test endpoint", "test REST/GraphQL", "check permission API", "IDOR", or when a UI case needs an API-level check.
argument-hint: "<RUN_ID> <STREAM_ID> [--env <name>] [--case TC_ID]"
---

# API testing with Hurl

API cases run without a browser, so they are fast, exact and cheap to repeat. They follow the `test-case-standard` format and the same PASS/FAIL/BLOCKED rules as browser cases; only the execution tool differs. Tool: [Hurl](https://hurl.dev) (plain-text HTTP requests with asserts; tested with Hurl 8.1.0).

```bash
SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)   # the skills folder testkit installed into
API=$SK/api-testing/scripts/api_run.py
hurl --version     # missing? `testkit doctor` lists the install command for this OS
```

## 1. Writing API cases (script-writer)

Write them in `cases/<STREAM_ID>.md` like every other case, with `Type: api` and these fields:

```markdown
### TC-S2-004 — Member cannot read another member's order (IDOR)
- Priority: P0
- Type: api
- Requirement: AC-3 (orders are private)
- Endpoint: GET /api/orders/{id}
- Auth: `{{member}}` (bearer token from POST /api/auth/login); resource owned by `{{member2}}`
- Preconditions: `{{member2}}` has at least one order.
- Request: no body. `{id}` = an order id of `{{member2}}`.
- Expected:
  - Status 404 (docs: "not found, never 403, to avoid leaking existence").
  - Body `$.error.code` = `NOT_FOUND`; body has no `$.owner` or other order fields.
  - Header `Content-Type` contains `application/json`.
- Source: docs/api.md#orders, src/routes/orders.ts:88
```

Rules on top of `test-case-standard`:

- **One behaviour per case, several requests allowed.** Login, setup and cleanup requests belong in the same case; the asserts are what the case checks.
- **Name the auth role** (`{{member}}`, `{{admin}}`, `anonymous`) and, for a second account of the same role, `{{member2}}`. Never paste tokens.
- **Expected status is exact** (`422`, not "4xx") and comes from the docs or the code's error handler. Body checks use JSONPath (`$.error.code`); schema checks name the schema (`components.schemas.Order` in `docs/openapi.yaml`).
- **Endpoints come from evidence** — the OpenAPI file, the route code, or a network log — and the case's `Source` says which. See `references/discovery.md`.
- Mix freely: a browser case can end with "Expected: GET /api/orders/{id} returns status `cancelled`" and the executor checks it with a one-off Hurl request.

What to cover for every changed endpoint (details and Hurl snippets: `references/hurl-patterns.md`):

| Area | Cases |
|---|---|
| Auth | no token → 401; expired/garbage token → 401; correct token → 2xx |
| Permission matrix | every role × every method on the endpoint (decision table), plus anonymous |
| IDOR | another user's / tenant's id in path, query and body (`owner_id`, `tenant_id`) |
| Validation | each required field missing; wrong type; boundaries min-1/min/max/max+1; edge strings from `test-data --edge` |
| Error format | status, error code, message, field errors match the documented shape; no stack traces or SQL in bodies |
| Lists | pagination first/last/beyond-last page, page size limits, sort + filter combined, empty list |
| Duplicates | same request twice; `Idempotency-Key` replay; unique constraint conflict → 409 |
| Files | allowed type, wrong type, oversize, zero-byte, unicode filename |
| GraphQL | query, mutation, field-level permission, `errors[]` shape, introspection setting per environment |

## 2. Executing API cases (test-executor)

1. **Accounts first.** Create the stream's accounts as usual (`test-executor` → Test accounts) and record them in `qa/accounts.local.json` under `runs.<RUN_ID>.<STREAM_ID>`. The runner turns them into Hurl variables: `member_email` and the secret `member_password`; a second `member` becomes `member2_*`.
2. **Write one file per case**: `qa/runs/<RUN_ID>/api/<STREAM_ID>/<TC_ID>.hurl`, first line `# <TC_ID> — <title>`. Use `{{base_url}}` for every URL (the runner refuses other hosts), `{{prefix}}` in names of data you create, and `redact` on token captures:

   ```hurl
   # TC-S2-004 — Member cannot read another member's order (IDOR)
   POST {{base_url}}/api/auth/login
   {"email": "{{member2_email}}", "password": "{{member2_password}}"}
   HTTP 200
   [Captures]
   owner_token: jsonpath "$.token" redact

   GET {{base_url}}/api/orders?per_page=1
   Authorization: Bearer {{owner_token}}
   HTTP 200
   [Captures]
   foreign_id: jsonpath "$.data[0].id"

   POST {{base_url}}/api/auth/login
   {"email": "{{member_email}}", "password": "{{member_password}}"}
   HTTP 200
   [Captures]
   token: jsonpath "$.token" redact

   GET {{base_url}}/api/orders/{{foreign_id}}
   Authorization: Bearer {{token}}
   HTTP 404
   [Asserts]
   jsonpath "$.error.code" == "NOT_FOUND"
   jsonpath "$.owner" not exists
   ```

3. **Check, then run** (from the project root):

   ```bash
   uv run $API check --run PROJ-123 --stream S2 --env staging   # safety only, sends nothing
   uv run $API run   --run PROJ-123 --stream S2 --env staging   # all files of the stream
   uv run $API run   --run PROJ-123 --stream S2 --case TC-S2-004 # re-run one case
   uv run $API vars  --run PROJ-123 --stream S2                  # what the files receive (secrets as ***)
   ```

   Per case the runner writes `evidence/<STREAM_ID>/api/<TC_ID>/` (`report.json`, `store/` with response bodies, `junit.xml`, `hurl.log`) and refreshes `evidence/<STREAM_ID>/api/summary.md`, a table of every case's status. Tokens, passwords and secret values are redacted from all of it.
4. **Record results** in `results/<STREAM_ID>.md` like browser cases; Evidence = `evidence/S2/api/TC-S2-004/`. Map runner statuses:

   | Runner | Result | What to do |
   |---|---|---|
   | `PASS` | PASS | — |
   | `FAIL` | FAIL | Read `hurl.log` (it shows the response). Re-run the case once (`--case`). Still failing → bug; put the request (curl line from `hurl.log`, token shown as `***`), status and body excerpt in the bug. |
   | `ERROR` | BLOCKED or FAIL | `HTTP connection` → environment down → BLOCKED. A capture that found nothing (login returned no token) → usually a product FAIL; decide from `hurl.log`. |
   | `CASE-ERROR` | — | Your `.hurl` file has a syntax error: fix it and re-run. |
   | `BLOCKED` | BLOCKED | Not sent: the safety check refused it (write method on `allow_write: false`, foreign host). |

5. Clean up data the stream created (section 4).

### Config

```yaml
api:
  base_urls: {}                 # optional per environment, e.g. {staging: https://api.staging.example.com};
                                #   default: environments.<env>.base_url
  openapi: ""                   # OpenAPI/Swagger file or URL path, e.g. docs/openapi.yaml or /openapi.json
  read_only_posts: [/api/auth/login, /graphql]   # POSTs allowed on allow_write: false environments
  vars: {}                      # extra plain Hurl variables, e.g. {tenant: acme}
  secrets_env: {}               # Hurl secrets from env vars, e.g. {admin_api_key: TESTKIT_API_ADMIN_KEY}
  max_parallel: 1               # hurl --jobs
  delay_ms: 100                 # pause before each request
  hurl_args: []                 # extra hurl flags, e.g. [--insecure] for a self-signed staging cert
```

No `api` block is needed for a first run: the runner falls back to the environment's `base_url` and these defaults.

## 3. Safety

- The runner sends requests only to `{{base_url}}` or hosts of environments in `qa/config.yml`. On an environment with `allow_write: false` it refuses PUT/PATCH/DELETE, GraphQL mutations, and POST to any path not listed in `api.read_only_posts` (login, GraphQL queries); those cases become `BLOCKED`.
- **Do not hammer.** The runner sends one request at a time with `api.delay_ms` between requests (default 100). Never loop requests to probe rate limits or brute-force logins; check a rate limit only when a case asks for it, with the smallest number of requests that proves it (`limit + 1`), and only on a non-production environment. A 429 you did not expect is an observation, not a reason to retry harder.
- Secrets reach Hurl only as `HURL_SECRET_*` environment variables (from `qa/accounts.local.json` or `api.secrets_env`). Never write tokens or passwords into `.hurl` files, results or bugs. The plain-variables file `api/<STREAM_ID>/.vars.env` holds no secrets.
- Do not capture into a variable whose name the runner already provides (`admin_token` from `api.secrets_env`, `member_email`, ...): pick a different name.
- IDOR and permission checks use only the stream's own accounts. Never enumerate ids of real users.

## 4. Test data and cleanup

Name everything you create with `{{prefix}}` (`proj-123-s2`) so parallel streams do not collide and cleanup can find it. For bulk data generate it with the `test-data` skill and load it with a Hurl file or the project's seed command. Delete what the stream created at the end (a `zz-cleanup.hurl` file that runs last, or `test_data.cleanup_command` from config); list anything you could not delete in the results.

## 5. Other runners

If the team already keeps Postman or Bruno collections, run those instead of rewriting them — see `references/discovery.md` → "Existing collections". Hurl stays the default for new cases.

## References

- `references/hurl-patterns.md` — Hurl recipes for every area in the coverage table, schema validation.
- `references/discovery.md` — finding endpoints (OpenAPI, routes, browser network log); Newman and Bruno.
