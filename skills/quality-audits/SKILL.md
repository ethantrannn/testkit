---
name: quality-audits
description: Non-functional checks a tester runs on the screens and APIs of a ticket or release — accessibility (axe-core WCAG 2.1 AA scan, keyboard-only and focus-visible walk), front-end performance (LCP, CLS, TBT, Navigation Timing under network/CPU throttling, budgets, optional Lighthouse), visual comparison against baselines or Figma exports, API load smoke tests with k6, and a security baseline (headers, cookies, CORS, TLS, exposed debug paths, OWASP ZAP baseline). Writes raw results plus a summary with severities ready to become bugs. Use when asked for an audit, "accessibility check", "a11y", "WCAG", "performance", "Lighthouse", "Core Web Vitals", "visual regression", "so sánh giao diện với Figma", "load test", "k6", "security headers", "ZAP", "kiểm thử hiệu năng", "kiểm thử bảo mật", "kiểm thử truy cập", or when a plan lists audit streams.
argument-hint: "<RUN_ID | release name> [a11y | perf | visual | load | security | all] [screens or URLs]"
---

# Quality audits

Non-functional checks on the screens, flows and endpoints of one ticket (`qa/runs/<RUN_ID>/`) or a release (`qa/releases/<name>/`). Every audit leaves raw machine output **and** a short human summary that maps each finding to a testkit severity, so the lead can file bugs with the `bug-reporting` skill.

```bash
SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)   # the skills folder testkit installed into
QA=$SK/quality-audits/scripts
BU=$SK/browser-testing/scripts/bu-session.sh
```

## 1. Before you start

1. Read `qa/config.yml`: `environments`, `audits` (section 6) and `project.language`.
2. Pick the scope: the screens/routes and endpoints the ticket touches (from `plan.md` and the cases), not the whole site. A release audit takes the release's main flows.
3. Gate every audit kind on the environment:

   ```bash
   uv run $QA/audit_guard.py <a11y|performance|visual|headers|load|security> <env>
   ```

   Exit 0 = allowed (prints `base_url` and the `audits.<kind>` settings). Exit 3 = refused: stop that audit and report the `reason`. `load` and `security` need the environment in `audits.<kind>.allowed_envs`, and are refused on production whatever the config says. Light audits (a11y, performance, visual, headers) run on any listed environment.
4. **Ask the user before** a k6 run and before a ZAP scan, even when allowed, stating the target, load and duration. Never widen limits on your own.
5. Logged-in screens: create or reuse a test account the way the `test-executor` agent does (`qa/accounts.local.json`), log in inside the browser session, then audit. Never write secrets into audit files.

## 2. Output layout

```
qa/runs/<RUN_ID>/audits/            (or qa/releases/<name>/audits/)
  summary.md                        one summary for all audits run (assets/audit-summary.md)
  a11y/<screen>-axe.json            raw axe results
  a11y/<screen>-keyboard.json       tab order, focus indicator, unreachable controls
  a11y/<screen>-nofocus-NN.png      screenshots of focus stops without a visible indicator
  perf/<screen>-<profile>-perf.json browser metrics per throttling profile
  perf/lighthouse-<screen>.report.{json,html}, lighthouse-<screen>.summary.json
  visual/<screen>@<WxH>.png, <screen>@<WxH>-diff.png, -diff.json
  load/<name>.js, <name>-summary.json, <name>-stdout.txt
  security/headers.json, security/<screen>-cookies.json, security/zap-report.{html,json,md}
qa/baselines/<screen>@<WxH>.png     approved visual baselines (committed, shared across runs)
```

`<screen>` is a short kebab-case name (`checkout`, `login`), `<profile>` is `desktop` or `mobile`.

## 3. Browser audits (a11y, performance, cookies)

All browser work follows the `browser-testing` skill (one session per stream, `$BU stop` at the end). Load the helpers once per snippet:

```bash
$BU run PROJ-123-A11Y <<'PY'
import glob; exec(open(glob.glob(".*/skills/quality-audits/scripts/browser_audits.py")[0]).read())
new_tab("https://staging.example.com/checkout"); wait_for_load()
print(qa_axe("qa/runs/PROJ-123/audits/a11y/checkout"))           # WCAG 2.1 A+AA by default
print(qa_keyboard("qa/runs/PROJ-123/audits/a11y/checkout"))
PY
```

| Helper | Does | Details |
|---|---|---|
| `qa_axe(base, tags=None, include=None, exclude=None, disable_rules=None)` | injects pinned axe-core 4.14.0 (sha256-checked, cached in `qa/.cache/`), runs `axe.run` | `references/accessibility.md` |
| `qa_keyboard(base, max_tabs=60)` | Tab-only walk: order, missing focus indicator, keyboard trap, clickable elements that cannot be focused | `references/accessibility.md` |
| `qa_perf(url, base, network, cpu, budgets)` | throttled cold load, Navigation Timing, FCP, LCP, CLS, long tasks, `Performance.getMetrics`, budget check | `references/performance.md` |
| `qa_cookies(base)` | Secure/HttpOnly/SameSite of the session's cookies after login (values never stored) | `references/security-baseline.md` |

Each returns a short dict: print it, and open the JSON only for detail. Open every screenshot you rely on.

## 4. Command-line audits

| Audit | Command | Reference |
|---|---|---|
| Lighthouse (optional, Node ≥ 22.19) | `npx -y lighthouse@13.6.0 <url> --output=json --output=html --output-path=<dir>/lighthouse-<screen> ...` then `python3 $QA/lighthouse_summary.py <...>.report.json --budget lcp_ms=2500 --min-score performance=0.8` | `references/performance.md` |
| Visual diff | `uv run $QA/visual_diff.py qa/baselines/<s>@<vp>.png <current>.png --out <diff>.png --json <diff>.json` | `references/visual-comparison.md` |
| Load smoke (k6) | copy `assets/k6-smoke.js`, `k6 run <file> -e BASE_URL=... -e VUS=2 -e DURATION=30s -e SUMMARY=...` | `references/load-testing.md` |
| Security headers | `python3 $QA/header_check.py <url> [<api url>] [--probe] --json <dir>/headers.json` | `references/security-baseline.md` |
| ZAP baseline (Docker) | `docker run --rm ... zaproxy/zap-stable:2.17.0 zap-baseline.py -t <url> ...` | `references/security-baseline.md` |

Read the reference before running an audit kind for the first time in a session; it has the exact flags, the pitfalls and how to read the output.

## 5. From findings to bugs

Write `audits/summary.md` from `assets/audit-summary.md` in `project.language` (keep IDs, statuses, severities, rule ids in English). One row per finding **group** (one axe rule on one screen, one failed budget, one visual region, one missing header across all pages), not per DOM node.

Default severity mapping (the lead may raise a severity when the finding blocks a core flow, or lower it for an internal tool):

| Source | blocker / critical | major | minor | trivial |
|---|---|---|---|---|
| axe impact | `critical` → critical | `serious` → major | `moderate` → minor | `minor` → trivial |
| Keyboard | trap, or a core action unreachable by keyboard → critical | no visible focus on a primary control → major | wrong but usable order → minor | |
| Performance budget | metric > 2× budget on a core page → major | over budget → minor | | |
| Visual diff | missing/overlapping element → major | changed layout, colour, copy vs approved design → minor | 1–2 px shift → trivial | |
| k6 thresholds | error rate over threshold → critical | p95 over threshold → major | | |
| Security | per `header_check.py` severity; ZAP `FAIL` (High) → critical, `WARN` Medium → major, Low → minor, Informational → not a bug | | | |

Rules:

- **Reproduce before filing**: rerun the failing audit once (perf: 3 runs, take the median). Lab numbers vary; file a perf bug only when the median misses the budget.
- **Accepted exceptions** live in config (`audits.a11y.ignore_rules`, ZAP rules file) with a reason; list them in the summary, do not file them.
- Do not file duplicates: a missing header on every page is one bug; one axe rule on a shared component is one bug listing the screens.
- A bug from an audit uses `test_case: AUDIT-<kind>-<screen>` when no TC covers it, `Steps to reproduce` = the exact command or snippet, `Evidence` = the JSON/PNG paths.
- The executor or orchestrator never edits `qa/bugs/index.md`; hand the finding list to the test-lead as the `bug-reporting` skill says.

## 6. Configuration (`qa/config.yml`)

```yaml
audits:
  a11y:
    tags: [wcag2a, wcag2aa, wcag21a, wcag21aa]   # axe-core runOnly tags
    fail_on: [critical, serious]                  # impacts that make the audit FAIL
    ignore_rules: []                              # accepted exceptions, e.g. [region]; give the reason in summary.md
  performance:
    profiles:                                     # each audited screen runs once per profile
      desktop: {network: none, cpu: 1}
      mobile: {network: slow-4g, cpu: 4, viewport: [375, 812]}
    budgets: {lcp_ms: 2500, cls: 0.1, tbt_ms: 300, fcp_ms: 1800, ttfb_ms: 800, transfer_kb: 1600}
    lighthouse: auto                              # auto: run when Node >= 22.19 exists | off
    lighthouse_min_scores: {performance: 0.8, accessibility: 0.9}
  visual:
    threshold_pct: 0.01                           # max changed pixels in %, per screenshot
    tolerance: 16                                 # per-pixel colour distance treated as equal
    viewports: [[1280, 720], [375, 812]]
  load:
    allowed_envs: []                              # e.g. [staging]; empty = load tests off. Never production.
    max_vus: 10
    max_duration: 1m
    p95_ms: 800
    error_rate: 0.01
    token_env: TESTKIT_API_TOKEN                  # optional: env var NAME holding a bearer token
  security:
    allowed_envs: []                              # ZAP baseline + debug-path probing; never production
    zap_image: zaproxy/zap-stable:2.17.0
    zap_minutes: 2                                # spider time
    zap_rules_file: qa/zap-rules.tsv              # optional: rule id -> IGNORE/INFO/FAIL
```

Mark a production environment with `production: true` under `environments.<name>` if its name is not `prod`, `production`, `prd` or `live`.

## 7. Tools

| Tool | Needed for | Install |
|---|---|---|
| `uv` | `visual_diff.py`, `audit_guard.py` (Pillow 13.0.0, PyYAML 6.0.3 pinned inline) | already required by testkit |
| browser-use + Chrome | a11y, performance, cookies | `browser-testing` skill |
| Node ≥ 22.19 + `npx` | Lighthouse 13.6.0 (optional) | nodejs.org / `brew install node` / `winget install OpenJS.NodeJS.LTS` |
| k6 | load smoke | `brew install k6` / apt `k6` from the Grafana repo / `winget install GrafanaLabs.k6` |
| Docker | ZAP baseline (optional, ~1.1 GB image) | Docker Desktop / `apt install docker.io` / `winget install Docker.DockerDesktop` |

Missing an optional tool: skip that part, say so in `summary.md` (status `NOT RUN` with the reason), never fake numbers.
