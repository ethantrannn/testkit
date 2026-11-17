# Finding endpoints, and running existing collections

## Finding the endpoints a ticket touches

Write API cases only for endpoints you found evidence for, and put that evidence in the case's `Source`. Look in this order.

### 1. OpenAPI / Swagger file

`api.openapi` in `qa/config.yml` names it. If empty, search the repo:

```bash
git ls-files | grep -iE '(openapi|swagger)[^/]*\.(ya?ml|json)$'
grep -rlE --include='*.yml' --include='*.yaml' --include='*.json' '^(openapi|swagger):|"(openapi|swagger)":' docs api spec 2>/dev/null | head
```

Many frameworks serve the spec at runtime: try `{{base_url}}/openapi.json`, `/v3/api-docs` (Spring), `/swagger/v1/swagger.json` (.NET), `/api-docs`, `/docs-json` (NestJS), `/openapi.yaml` — on a configured environment only. List the operations quickly:

```bash
python3 - docs/openapi.json <<'PY'
import json, sys
spec = json.load(open(sys.argv[1]))
for path, ops in spec.get("paths", {}).items():
    for method, op in ops.items():
        if method in {"get", "post", "put", "patch", "delete"}:
            print(method.upper(), path, "|", op.get("summary", ""), "| security:", op.get("security", spec.get("security", "")))
PY
```

(For YAML, `uv run --with PyYAML==6.0.3 python3 -c ...` with `yaml.safe_load`.) Use the spec for status codes, required fields, enums, `maxLength`/`maximum` (boundaries), `security` (auth cases) and `components.schemas` (schema checks). Where the spec and the code disagree, write the case to the docs and add the conflict to `Assumptions`.

### 2. Routes in code

Search `code.paths` for route declarations, then read the handler for validation rules, permission checks and error codes:

| Stack | Search for |
|---|---|
| Express / Fastify / Hono | `router.get(`, `app.post(`, `fastify.route(`, `.get("/` |
| NestJS | `@Controller(`, `@Get(`, `@Post(`, guards `@UseGuards(`, `@Roles(` |
| Next.js | `app/**/route.ts` exporting `GET`/`POST`, `pages/api/**` |
| Django / DRF | `urls.py` `path(`, `ViewSet`, `permission_classes` |
| FastAPI / Flask | `@app.get(`, `@router.post(`, `@bp.route(`, `Depends(` |
| Rails | `config/routes.rb`, `before_action :authorize` |
| Laravel | `routes/api.php`, `->middleware(` |
| Spring | `@RestController`, `@GetMapping`, `@PreAuthorize` |
| Go | `HandleFunc(`, `r.GET(`, `e.POST(` |
| GraphQL | `type Query`, `type Mutation` in `*.graphql`, resolvers, `@auth`/`@hasRole` directives |

Validation sources: zod/yup/joi/class-validator schemas, Pydantic models, DRF serializers, Rails validations, DB constraints in migrations (`NOT NULL`, `UNIQUE`, `VARCHAR(n)`).

### 3. Browser network log

When docs and code are thin, let the app show you. While exploring with `browser-testing`, every request the page makes is in the session's network events. `tk_evidence(...)` writes failed ones to `<base>.json`; to list all API calls of a screen, read the network events in the session (browser-use: the `browser-use` skill's network section; agent-browser: `network requests`). Record method, path, status, request body keys and the auth header type (never the token value) in the case's `Source` as `network log, <screen>`.

### 4. Ask

If an endpoint the ticket mentions is in none of these, put it in `Assumptions` as a question; do not guess paths against a shared environment.

## Existing collections (Newman, Bruno)

If the team already maintains a Postman or Bruno collection that covers the ticket, run it and record its results as the evidence of the cases it covers; write new cases in Hurl. Both tools are Node-based and run through `npx`, so nothing is installed globally. They are optional; ask before adding them to a project.

Configure in `qa/config.yml`:

```yaml
api:
  collections:
    - tool: newman            # newman | bruno
      path: postman/app.postman_collection.json   # bruno: the collection folder
      environment: postman/staging.postman_environment.json   # bruno: env name, e.g. staging
```

Keep the same safety rules: the collection's base URL must be a configured environment, secrets come from environment variables, and collections that write data run only where `allow_write: true`.

### Postman → Newman

```bash
EV=qa/runs/PROJ-123/evidence/S2/api/newman
mkdir -p "$EV"
npx -y newman@6.2.3 run postman/app.postman_collection.json \
  -e postman/staging.postman_environment.json \
  --env-var "baseUrl=https://staging.example.com" \
  --env-var "token=$TESTKIT_API_MEMBER_TOKEN" \
  --folder "Orders" --delay-request 100 \
  --reporters cli,json,junit \
  --reporter-json-export "$EV/report.json" \
  --reporter-junit-export "$EV/junit.xml"
```

`--folder` limits the run to the part of the collection the stream covers. Newman's JSON report contains request headers: check it for tokens before keeping it as evidence, and replace them with `***`.

### Bruno

```bash
EV=qa/runs/PROJ-123/evidence/S2/api/bruno
mkdir -p "$EV"
cd bruno/app-collection          # Bruno runs from inside the collection folder
npx -y @usebruno/cli@4.3.0 run orders --env staging \
  --env-var "token=$TESTKIT_API_MEMBER_TOKEN" \
  --reporter-json "$OLDPWD/$EV/report.json" \
  --reporter-junit "$OLDPWD/$EV/junit.xml" \
  --reporter-skip-all-headers
```

Map each collection request or folder to the TC IDs it covers in the results table, with the evidence path of the report.
