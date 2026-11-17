# API load smoke test (k6)

A small, short load against the APIs of a ticket to catch obvious problems: errors under a few concurrent users, p95 latency far above budget, rate-limit or connection-pool failures. It is **not** capacity testing; that needs a dedicated environment and the team's agreement.

## 1. Gate

```bash
uv run $QA/audit_guard.py load staging        # exit 0 = allowed; prints base_url and audits.load limits
```

- Runs only when the environment is in `audits.load.allowed_envs`, never on production (the guard refuses it even if listed).
- Ask the user before each run: target base URL, endpoints, VUs, duration. Stay within `max_vus` and `max_duration`.
- Read-only endpoints by default. Write endpoints only if `allow_write: true` for the environment **and** the data is test data you can clean up.
- Start with the defaults (2 VUs, 10 s). Increase only if that passes and the user agreed.

## 2. Prepare the script

```bash
mkdir -p qa/runs/PROJ-123/audits/load
cp $SK/quality-audits/assets/k6-smoke.js qa/runs/PROJ-123/audits/load/orders-api.js
```

Edit `ENDPOINTS` in the copy: `{ name, method, path, expect, body }`. Take paths from the ticket, the API docs or the network log you captured while exploring. For JSON bodies add `params.headers['Content-Type'] = 'application/json'` and `body: JSON.stringify({...})`.

Authentication: put the token in an environment variable and pass only its **name** (`-e TOKEN_ENV=TESTKIT_API_TOKEN`); the script reads the value with `__ENV`. Never write a token into the script or the command line. k6 does not print header values in its summary.

## 3. Run

```bash
L=qa/runs/PROJ-123/audits/load
k6 run $L/orders-api.js \
  -e BASE_URL=https://staging.example.com -e VUS=2 -e DURATION=10s \
  -e P95_MS=800 -e ERROR_RATE=0.01 -e TOKEN_ENV=TESTKIT_API_TOKEN \
  -e SUMMARY=$L/orders-api-summary.json --quiet > $L/orders-api-stdout.txt 2>&1
echo "k6 exit $?"      # 0 = thresholds met, 99 = a threshold was crossed, other = script/setup error
cat $L/orders-api-stdout.txt
```

The template uses a `constant-vus` scenario, `sleep(1)` per iteration, a `check` per request (expected status), and thresholds `http_req_failed rate<ERROR_RATE`, `http_req_duration p(95)<P95_MS`, `checks rate>0.99`. `handleSummary` writes the full JSON to `SUMMARY` and a short text summary (requests, rps, avg/p95/p99/max, failed %, each threshold PASS/FAIL) to stdout.

## 4. Read the result

| Field in `<name>-summary.json` | Meaning |
|---|---|
| `metrics.http_reqs.values.count` / `.rate` | requests sent / per second |
| `metrics.http_req_duration.values["p(95)"]` | 95th percentile latency in ms |
| `metrics.http_req_failed.values.rate` | share of requests with status ≥ 400 or network error |
| `metrics.checks.values.rate` | share of passed checks (wrong status codes) |
| `metrics.<m>.thresholds["<expr>"].ok` | threshold result |
| `metrics.http_req_duration{name:<endpoint>}` | per endpoint only if you add a threshold on that tag, e.g. `'http_req_duration{name:list items}': ['p(95)<500']` |

Before filing: rerun once; check the failures are not caused by your own test (expired token → 401, rate limiting the team configured → 429 that the docs mention). A 5xx under 2–10 VUs is a real finding (critical when it breaks a core API). Attach the summary JSON and stdout; never attach response bodies with personal data.

## 5. Summary rows

`LOAD-<name>` | env | VUs × duration | requests | p95 ms (threshold) | error rate (threshold) | result | severity | summary JSON path.
