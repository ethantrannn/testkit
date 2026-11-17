# Front-end performance audit

Lab measurements of the screens a ticket touches, in a real Chrome, under fixed throttling, against budgets from `audits.performance` in `qa/config.yml`. Lab numbers are for comparison and regression, not a promise about real users; say so in the summary.

## 1. Browser metrics (always available)

```bash
$BU run PROJ-123-PERF <<'PY'
import glob; exec(open(glob.glob(".*/skills/quality-audits/scripts/browser_audits.py")[0]).read())
new_tab("about:blank")
budgets = {"lcp_ms": 2500, "cls": 0.1, "tbt_ms": 300, "fcp_ms": 1800, "ttfb_ms": 800, "transfer_kb": 1600}
for run in (1, 2, 3):
    r = qa_perf("https://staging.example.com/checkout", f"qa/runs/PROJ-123/audits/perf/checkout-mobile-{run}",
                network="slow-4g", cpu=4, budgets=budgets)
    print(run, {k: r[k] for k in ("ttfb_ms", "fcp_ms", "lcp_ms", "lcp_element", "cls", "tbt_ms", "load_ms", "transfer_kb")},
          [(c["budget"], c["actual"], c["result"]) for c in r["budgets"]])
PY
```

What `qa_perf` does: brings the tab to front (hidden tabs never paint), disables the cache (cold load), applies `Network.emulateNetworkConditions` and `Emulation.setCPUThrottlingRate`, installs `PerformanceObserver`s for paint, `largest-contentful-paint`, `layout-shift` (without recent input) and `longtask` before any page script, navigates, waits for `load` plus `settle` seconds (default 3), reads Navigation Timing, resource timing and CDP `Performance.getMetrics`, then **resets all throttling**.

| `network` | latency | down / up kbit/s |
|---|---|---|
| `none` | – | – |
| `fast-4g` | 60 ms | 9000 / 1500 |
| `slow-4g` | 150 ms | 1600 / 750 (Lighthouse mobile) |
| `3g` | 2000 ms | 400 / 400 |

For the mobile profile also set the viewport first (`browser-testing` section 2), since LCP depends on what is in view.

Output `<base>-perf.json`: `ttfb_ms`, `fcp_ms`, `lcp_ms` + `lcp_element`, `cls` + `layout_shifts[]` (time, value, node names), `long_tasks`, `tbt_ms` (sum of long-task time over 50 ms after observers start; an approximation, use Lighthouse for a lab TBT), `load_ms`, `requests`, `transfer_kb`, `by_type`, `slowest[]` (top 8 resources), `cdp` (Nodes, JSHeapUsedSize, LayoutCount, ScriptDuration, TaskDuration…), `budgets[]` with PASS/FAIL.

Rules:

- **3 runs per screen and profile, report the median**. One slow run is noise.
- Logged-in screens: log in first in the same session; `qa_perf` navigates in that tab and keeps cookies.
- Interactions (open a dialog, filter a list): measure with `js("performance.now()")` before the click and `wait_for_element` after, or record a trace (`Tracing.start` / `Tracing.end`) only if the ticket is about that interaction.
- Do not run throttled loops against production pages more than the 3 runs above.

## 2. Lighthouse (optional, Node-native)

Use when `audits.performance.lighthouse` is `auto` and `node --version` is ≥ 22.19. Lighthouse 13.6.0 gives lab TBT/Speed Index and concrete opportunities.

```bash
export CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"   # if Lighthouse cannot find Chrome
OUT=qa/runs/PROJ-123/audits/perf
npx -y lighthouse@13.6.0 https://staging.example.com/checkout --quiet \
  --chrome-flags="--headless=new" --only-categories=performance,accessibility,best-practices \
  --output=json --output=html --output-path=$OUT/lighthouse-checkout          # mobile, simulated slow 4G by default
# desktop: add --preset=desktop and use the name lighthouse-checkout-desktop
python3 $QA/lighthouse_summary.py $OUT/lighthouse-checkout.report.json \
  --budget lcp_ms=2500 --budget cls=0.1 --budget tbt_ms=300 --min-score performance=0.8 \
  --json $OUT/lighthouse-checkout.summary.json
```

- Output files: `<path>.report.json` and `<path>.report.html` (keep the HTML for people).
- **Logged-in pages**: point Lighthouse at the browser-use session's Chrome so it reuses the login: `. qa/.browser-use/sessions/<session>.env; npx -y lighthouse@13.6.0 <url> --port=$PORT --disable-storage-reset ...` (isolated mode only). `--disable-storage-reset` stops Lighthouse from clearing that origin's storage.
- `lighthouse_summary.py` prints scores, metrics, a budget table and failing audits (Lighthouse 13 "insights" sorted by estimated savings). Exit 1 when a budget or minimum score is missed.
- Lighthouse scores move ±5 between runs; budget on metrics, use scores only as a coarse gate.

## 3. Reading results

| Symptom | Usually caused by | Put in the bug |
|---|---|---|
| High TTFB | slow backend/API, no caching | `ttfb_ms`, the URL, `navigation` timings |
| High LCP, `lcp_element` is an image | large/unoptimised image, lazy-loaded hero, late discovery | element, `slowest[]` entry, image bytes |
| High LCP, text element | render-blocking CSS/JS, web fonts | `slowest[]` scripts/styles before FCP |
| CLS > 0.1 | images without size, late banners, font swap | `layout_shifts[]` times and nodes, before/after screenshots |
| High TBT / long tasks | heavy JS on load | `long_tasks`, `cdp.ScriptDuration`, Lighthouse `bootup-time` |
| Big `transfer_kb` | uncompressed or duplicated bundles | `by_type`, `slowest[]` |

Summary row: `PERF-<screen>-<profile>` | metric | budget | median of 3 | result | severity (section 5 of SKILL.md) | evidence JSON paths.
