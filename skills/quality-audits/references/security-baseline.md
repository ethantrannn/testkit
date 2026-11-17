# Security baseline

A tester's first pass: passive checks that find common misconfigurations. It does not replace a penetration test; say so in the summary. Never attack: no fuzzing, no injection payloads, no brute force, no active ZAP scan.

## 1. Header, cookie, CORS, TLS check (any configured environment)

```bash
uv run $QA/audit_guard.py headers staging          # environment must be in qa/config.yml
S=qa/runs/PROJ-123/audits/security; mkdir -p $S
python3 $QA/header_check.py https://staging.example.com/ https://staging.example.com/api/me \
  --json $S/headers.json
```

A few GET/OPTIONS requests per URL (stdlib only, follows no redirects so it sees the real response). Pass the main page and one or two API URLs of the ticket. Checks and default severities:

| Check | Finding | Severity |
|---|---|---|
| `hsts` | HTTPS response without `Strict-Transport-Security`, or `max-age` < 180 days | major / minor |
| `csp` | no `Content-Security-Policy` (or only `-Report-Only`); `unsafe-inline` scripts or `*` default | major / minor |
| `nosniff` | no `X-Content-Type-Options: nosniff` | minor |
| `clickjacking` | no `X-Frame-Options` and no CSP `frame-ancestors` | minor (major on pages with sensitive actions) |
| `referrer-policy`, `permissions-policy` | missing | trivial / info |
| `version-leak` | `Server`/`X-Powered-By` reveal a version or stack | minor / trivial |
| `cookie` | `Set-Cookie` without `Secure` (HTTPS), `HttpOnly`, `SameSite`; `SameSite=None` without `Secure` | major for session-like names (`sess`, `sid`, `auth`, `token`, `jwt`), else minor |
| `cors` | reflects a foreign `Origin` (default `https://evil.example`) with `Allow-Credentials: true` | critical |
| `https` | HTTP not redirected to HTTPS; site on plain HTTP (localhost is info only) | major |
| `tls` | certificate expiring < 30/14 days or expired; server accepts TLS 1.0/1.1 | minor / major / critical |

Exit 1 when any finding is major or worse. The JSON has `pages[].headers` (no cookie values), `pages[].tls`, `findings[]`.

**Cookies set after login** are not visible to a plain GET. After logging in inside the browser session:

```bash
$BU run PROJ-123-SEC <<'PY'
import glob; exec(open(glob.glob(".*/skills/quality-audits/scripts/browser_audits.py")[0]).read())
print(qa_cookies("qa/runs/PROJ-123/audits/security/after-login"))   # flags only, values never stored
PY
```

## 2. Exposed debug and secret paths (`--probe`, allowed envs only)

```bash
uv run $QA/audit_guard.py security staging && \
python3 $QA/header_check.py https://staging.example.com/ --probe --json $S/headers.json
```

GETs ~15 well-known paths on the origin (`/.env`, `/.git/config`, `/actuator/env`, `/actuator/heapdump`, `/server-status`, `/phpinfo.php`, `/debug`, `/swagger-ui/`, GraphQL introspection, `/backup.zip` …). A random path is fetched first so single-page-app catch-all pages are not reported. Only the status, type and size are recorded, never the content. Open a hit in the browser only to confirm, and do not copy secrets into the bug: write "file exposes database credentials (not copied)".

## 3. OWASP ZAP baseline scan (Docker, allowed envs only, ask first)

Passive only: ZAP spiders the site for a few minutes and reports what it sees in the responses; it does not send attacks. Still, it crawls every link it finds, so:

- environment must pass `audit_guard.py security <env>`; never production;
- ask the user first (target URL, spider minutes, that it can follow any link, including "delete" links if they are plain GET links on an `allow_write: false` env, which is itself a bug);
- the image `zaproxy/zap-stable:2.17.0` is about 1.1 GB; pulling it is the user's decision.

```bash
S=qa/runs/PROJ-123/audits/security; mkdir -p $S && chmod a+w $S       # the container runs as user zap (uid 1000)
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd)/$S:/zap/wrk/:rw" zaproxy/zap-stable:2.17.0 \
  zap-baseline.py -t https://staging.example.com -m 2 -T 10 -I \
  -r zap-report.html -J zap-report.json -w zap-report.md
echo "zap exit $?"     # 0 pass, 1 FAIL rules hit, 2 WARN only (with -I: 0), 3 ZAP error
```

| Flag | Meaning |
|---|---|
| `-t URL` | target (one of the configured environments) |
| `-m 2` | spider minutes (`audits.security.zap_minutes`) |
| `-T 10` | max minutes for passive scan to finish |
| `-I` | do not fail on warnings (we classify ourselves) |
| `-c zap-rules.tsv` | rules file in the mounted folder: `<rule id>\tIGNORE|INFO|WARN|FAIL\t<comment>`; generate the default list with `-g zap-rules.tsv` |
| `-j` | also run the AJAX spider (SPAs); slower |
| `-r / -J / -w` | HTML / JSON / Markdown report, written into the mounted folder |

- Local targets: from inside Docker use `http://host.docker.internal:3000` (macOS/Windows) or add `--network=host` on Linux.
- Git Bash on Windows: keep `MSYS_NO_PATHCONV=1` so `/zap/wrk` is not rewritten; use `"$(pwd -W)/$S"` if the mount is empty.

Reading `zap-report.json`: `site[].alerts[]` with `pluginid`, `alert` (name), `riskdesc` (`High (Medium)` = risk (confidence)), `count`, `instances[].uri`, `solution`, `reference`, `cweid`. Map risk: High → critical, Medium → major, Low → minor, Informational → not a bug (mention in summary). Low-confidence alerts: confirm with the header check or the browser before filing. Many ZAP baseline alerts duplicate `header_check.py` findings; file each issue once.

## 4. Summary rows

`SEC-<check>` | finding | URLs affected | severity | source (`header_check` / `cookies` / `zap:<pluginid>`) | evidence path. Group a header missing on many URLs into one row.
