"""testkit quality-audit helpers for browser-use sessions (accessibility, keyboard, performance, cookies).

Load inside a bu-session snippet (the browser-use helpers cdp, js, page_info, capture_screenshot are
already defined there), from the project root:

    import glob; exec(open(glob.glob(".*/skills/quality-audits/scripts/browser_audits.py")[0]).read())

    qa_axe("qa/runs/R/audits/a11y/checkout")              axe-core scan -> checkout-axe.json, returns summary
    qa_keyboard("qa/runs/R/audits/a11y/checkout")         Tab walk + focus-visible -> checkout-keyboard.json
    qa_perf("https://staging.example.com/checkout", "qa/runs/R/audits/perf/checkout",
            network="slow-4g", cpu=4, budgets={"lcp_ms": 2500, "cls": 0.1})
                                                          throttled load -> checkout-perf.json
    qa_cookies("qa/runs/R/audits/security/cookies")       cookie flags of the current session

Every function writes raw JSON next to the base path and returns a short dict to print.
No third-party packages: the axe-core bundle is downloaded once (pinned version, sha256 checked) and
cached in qa/.cache/.
"""
import hashlib
import json
import os
import time
import urllib.request

AXE_VERSION = "4.14.0"
AXE_SHA256 = "20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878"
AXE_URLS = [
    "https://cdnjs.cloudflare.com/ajax/libs/axe-core/{v}/axe.min.js",
    "https://cdn.jsdelivr.net/npm/axe-core@{v}/axe.min.js",
]
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]
IMPACT_ORDER = ["critical", "serious", "moderate", "minor"]
# impact -> testkit bug severity (bug-reporting skill); the lead may raise it for core flows.
IMPACT_SEVERITY = {"critical": "critical", "serious": "major", "moderate": "minor", "minor": "trivial"}

# DevTools throttling presets: latency ms, down/up kbit/s.
NETWORK_PRESETS = {
    "none": None,
    "fast-4g": (60, 9000, 1500),
    "slow-4g": (150, 1600, 750),   # Lighthouse mobile default
    "3g": (2000, 400, 400),
}


def _write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def _eval(expression, timeout=60.0):
    r = cdp("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True,
            _response_timeout=timeout)
    if r.get("exceptionDetails"):
        d = r["exceptionDetails"]
        raise RuntimeError((d.get("exception") or {}).get("description") or d.get("text"))
    return (r.get("result") or {}).get("value")


def _axe_source(version=AXE_VERSION, sha256=AXE_SHA256, cache_dir="qa/.cache"):
    path = os.path.join(cache_dir, f"axe-core-{version}.min.js")
    if os.path.exists(path):
        return open(path, encoding="utf-8").read()
    last = None
    for u in AXE_URLS:
        try:
            body = urllib.request.urlopen(u.format(v=version), timeout=30).read()
        except Exception as e:  # try the next CDN
            last = e
            continue
        if sha256 and hashlib.sha256(body).hexdigest() != sha256:
            raise RuntimeError(f"axe-core {version} from {u} failed the sha256 check; not injecting it")
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "wb") as f:
            f.write(body)
        return body.decode("utf-8")
    raise RuntimeError(f"could not download axe-core {version} ({last}); put axe.min.js at {path}")


def _inject_source(src, chunk=30000):
    """Evaluate a large script in the page. The browser-use IPC caps one message at 64 KiB, so the
    source is sent in chunks and evaluated with an indirect eval. If the page CSP forbids eval,
    CSP is bypassed for this tab and the page reloaded once."""
    for attempt in (1, 2):
        _eval("window.__tkSrc = []; true")
        for i in range(0, len(src), chunk):
            _eval("window.__tkSrc.push(%s); true" % json.dumps(src[i:i + chunk]))
        try:
            _eval("(() => { const s = window.__tkSrc.join(''); delete window.__tkSrc; (0, eval)(s); return true; })()", 60)
            return
        except RuntimeError as e:
            if attempt == 2 or "EvalError" not in str(e):
                raise
            cdp("Page.setBypassCSP", enabled=True)
            cdp("Page.reload", ignoreCache=False)
            time.sleep(0.5)
            wait_for_load()


def qa_axe(out_base, tags=None, include=None, exclude=None, disable_rules=None,
           version=AXE_VERSION, sha256=AXE_SHA256):
    """Inject axe-core into the current page and run it. Writes <out_base>-axe.json (raw results).

    tags: axe tags (default WCAG 2.1 A + AA). include/exclude: CSS selectors to scope the scan.
    disable_rules: rule ids to skip (e.g. accepted exceptions from config).
    """
    tags = tags or AXE_TAGS
    if not _eval("typeof window.axe !== 'undefined' && !!window.axe.run"):
        _inject_source(_axe_source(version, sha256))
    ctx = {}
    if include:
        ctx["include"] = [[s] for s in include]
    if exclude:
        ctx["exclude"] = [[s] for s in exclude]
    opts = {"runOnly": {"type": "tag", "values": tags}, "resultTypes": ["violations", "incomplete"]}
    if disable_rules:
        opts["rules"] = {r: {"enabled": False} for r in disable_rules}
    expr = ("axe.run(%s, %s).then(r => ({url: r.url, timestamp: r.timestamp, testEngine: r.testEngine,"
            " testEnvironment: r.testEnvironment, toolOptions: r.toolOptions, violations: r.violations,"
            " incomplete: r.incomplete, passes: r.passes.length, inapplicable: r.inapplicable.length}))"
            % (json.dumps(ctx) if ctx else "document", json.dumps(opts)))
    res = _eval(expr, timeout=180)
    raw = _write_json(out_base + "-axe.json", res)
    by_impact = {k: 0 for k in IMPACT_ORDER}
    rows = []
    for v in sorted(res["violations"], key=lambda v: IMPACT_ORDER.index(v.get("impact") or "minor")):
        imp = v.get("impact") or "minor"
        by_impact[imp] += 1
        rows.append({"rule": v["id"], "impact": imp, "severity": IMPACT_SEVERITY[imp],
                     "nodes": len(v["nodes"]), "help": v["help"], "helpUrl": v["helpUrl"],
                     "wcag": [t for t in v["tags"] if t.startswith("wcag") and t[4:].isdigit()],
                     "targets": [" ".join(map(str, n["target"])) for n in v["nodes"][:5]]})
    return {"url": res["url"], "axe": version, "tags": tags, "violations": len(rows),
            "by_impact": by_impact, "incomplete": len(res["incomplete"]), "passes": res["passes"],
            "rules": rows, "raw": raw}


_FOCUS_JS = r"""
(() => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  const pick = s => ({outline: s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0 ? s.outlineStyle + ' ' + s.outlineWidth + ' ' + s.outlineColor : 'none',
                      boxShadow: s.boxShadow, border: s.borderTopColor + ' ' + s.borderTopWidth, bg: s.backgroundColor,
                      color: s.color, textDecoration: s.textDecorationLine});
  const focused = pick(getComputedStyle(el));
  const sel = (() => {
    if (el.id) return '#' + CSS.escape(el.id);
    let p = el, parts = [];
    while (p && p.nodeType === 1 && parts.length < 4) {
      let s = p.tagName.toLowerCase();
      if (p.classList.length) s += '.' + [...p.classList].slice(0, 2).map(c => CSS.escape(c)).join('.');
      const sib = p.parentElement ? [...p.parentElement.children].filter(c => c.tagName === p.tagName) : [];
      if (sib.length > 1) s += ':nth-of-type(' + (sib.indexOf(p) + 1) + ')';
      parts.unshift(s); p = p.parentElement;
    }
    return parts.join(' > ');
  })();
  const r = el.getBoundingClientRect();
  const name = (el.getAttribute('aria-label') || (el.labels && el.labels[0] ? el.labels[0].innerText : '') || el.innerText || el.value || el.getAttribute('placeholder') ||
                el.getAttribute('title') || el.getAttribute('alt') || '').trim().slice(0, 60);
  // Compare with the unfocused look: blur, read, refocus (keyboard modality is kept by Chrome).
  el.blur(); const blurred = pick(getComputedStyle(el)); el.focus({preventScroll: true});
  const changed = Object.keys(focused).filter(k => focused[k] !== blurred[k]);
  return {selector: sel, tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '', name,
          tabindex: el.getAttribute('tabindex'), focusVisible: el.matches(':focus-visible'),
          indicator: changed, focusedStyle: focused,
          rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
          offscreen: r.width === 0 || r.height === 0 || r.bottom < 0 || r.right < 0 ||
                     r.top > innerHeight + scrollY + 2000};
})()
"""

_CLICKABLE_NOT_FOCUSABLE_JS = r"""
(() => {
  const out = [];
  for (const el of document.querySelectorAll('[onclick], [role=button], [role=link], [role=checkbox], [role=tab], [role=menuitem]')) {
    const native = el.matches('a[href], button, input, select, textarea, summary, [contenteditable=""], [contenteditable=true]');
    if (!native && el.tabIndex < 0 && el.offsetParent !== null)
      out.push({tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '', text: (el.innerText || '').trim().slice(0, 60),
                html: el.outerHTML.slice(0, 120)});
  }
  return out;
})()
"""


def _tab(shift=False):
    mods = 8 if shift else 0
    for t in ("rawKeyDown", "keyUp"):
        cdp("Input.dispatchKeyEvent", type=t, key="Tab", code="Tab", windowsVirtualKeyCode=9,
            nativeVirtualKeyCode=9, modifiers=mods)


def qa_keyboard(out_base, max_tabs=60, screenshots=5):
    """Walk the page with Tab only, from the top. Writes <out_base>-keyboard.json.

    Reports the focus order, stops without a visible focus indicator (screenshots of the first few),
    a possible keyboard trap (focus stops cycling through new elements), and click handlers that
    keyboard users cannot reach.
    """
    _eval("window.scrollTo(0,0); document.activeElement && document.activeElement.blur(); true")
    stops, seen, missing, shots, trap = [], {}, [], [], None
    for i in range(1, max_tabs + 1):
        _tab()
        time.sleep(0.05)
        info = _eval(_FOCUS_JS)
        if info is None:
            if stops:
                break  # focus left the document: the cycle is complete
            continue
        info["n"] = i
        key = info["selector"]
        if key in seen:
            if stops and key == stops[0]["selector"]:
                break  # wrapped around to the first stop: cycle complete
            seen[key] += 1
            if seen[key] >= 3:
                trap = {"selector": key, "at_tab": i}
                break
        else:
            seen[key] = 1
        stops.append(info)
        if not info["indicator"]:
            missing.append({"n": i, "selector": key, "name": info["name"]})
            if len(shots) < screenshots:
                shots.append(capture_screenshot(f"{out_base}-nofocus-{i:02d}.png"))
    unreachable = _eval(_CLICKABLE_NOT_FOCUSABLE_JS) or []
    data = {"url": page_info().get("url"), "tab_presses": i, "stops": stops, "no_visible_focus": missing,
            "possible_trap": trap, "clickable_not_focusable": unreachable, "screenshots": shots}
    raw = _write_json(out_base + "-keyboard.json", data)
    return {"focus_stops": len(stops), "no_visible_focus": len(missing), "possible_trap": trap,
            "clickable_not_focusable": len(unreachable),
            "order": [f'{s["tag"]}{"[" + s["role"] + "]" if s["role"] else ""} "{s["name"]}"' for s in stops][:40],
            "screenshots": shots, "raw": raw}


_PERF_INIT_JS = r"""
window.__tkPerf = {lcp: null, lcpEl: null, cls: 0, shifts: [], fcp: null, longTasks: 0, tbt: 0};
try { new PerformanceObserver(l => { for (const e of l.getEntries()) { window.__tkPerf.lcp = e.startTime;
  window.__tkPerf.lcpEl = e.element ? (e.element.tagName.toLowerCase() + (e.element.id ? '#' + e.element.id : '') + (e.url ? ' ' + e.url : '')) : (e.url || null); } })
  .observe({type: 'largest-contentful-paint', buffered: true}); } catch (e) {}
try { new PerformanceObserver(l => { for (const e of l.getEntries()) { if (!e.hadRecentInput) { window.__tkPerf.cls += e.value;
  window.__tkPerf.shifts.push({t: Math.round(e.startTime), v: +e.value.toFixed(4), nodes: (e.sources || []).map(s => s.node ? s.node.nodeName : '?').slice(0, 3)}); } } })
  .observe({type: 'layout-shift', buffered: true}); } catch (e) {}
try { new PerformanceObserver(l => { for (const e of l.getEntries()) if (e.name === 'first-contentful-paint') window.__tkPerf.fcp = e.startTime; })
  .observe({type: 'paint', buffered: true}); } catch (e) {}
try { new PerformanceObserver(l => { for (const e of l.getEntries()) { window.__tkPerf.longTasks++; window.__tkPerf.tbt += Math.max(0, e.duration - 50); } })
  .observe({type: 'longtask', buffered: true}); } catch (e) {}
"""

_PERF_READ_JS = r"""
(() => {
  const n = performance.getEntriesByType('navigation')[0] || {};
  const res = performance.getEntriesByType('resource');
  const byType = {};
  for (const r of res) { const t = r.initiatorType || 'other'; byType[t] = byType[t] || {count: 0, bytes: 0};
    byType[t].count++; byType[t].bytes += r.transferSize || 0; }
  const slow = [...res].sort((a, b) => b.duration - a.duration).slice(0, 8)
    .map(r => ({url: r.name.slice(0, 160), type: r.initiatorType, ms: Math.round(r.duration), bytes: r.transferSize || 0}));
  const p = window.__tkPerf || {};
  return {
    url: location.href,
    ttfb_ms: Math.round(n.responseStart - n.startTime), dom_content_loaded_ms: Math.round(n.domContentLoadedEventEnd - n.startTime),
    load_ms: Math.round(n.loadEventEnd - n.startTime), fcp_ms: p.fcp && Math.round(p.fcp), lcp_ms: p.lcp && Math.round(p.lcp),
    lcp_element: p.lcpEl, cls: +(p.cls || 0).toFixed(4), layout_shifts: p.shifts, long_tasks: p.longTasks, tbt_ms: Math.round(p.tbt || 0),
    requests: res.length + 1, transfer_kb: Math.round((res.reduce((s, r) => s + (r.transferSize || 0), 0) + (n.transferSize || 0)) / 1024),
    by_type: byType, slowest: slow, navigation: n.toJSON ? n.toJSON() : null
  };
})()
"""

# budget key -> metric key; every budget is "lower is better".
BUDGET_KEYS = {"ttfb_ms": "ttfb_ms", "fcp_ms": "fcp_ms", "lcp_ms": "lcp_ms", "cls": "cls", "tbt_ms": "tbt_ms",
               "load_ms": "load_ms", "requests": "requests", "transfer_kb": "transfer_kb"}


def qa_perf(url, out_base, network="none", cpu=1, budgets=None, settle=3.0, timeout=60):
    """Load <url> with throttling and collect Navigation Timing, paint, LCP, CLS, long tasks and CDP metrics.

    network: none | fast-4g | slow-4g | 3g, or a (latency_ms, down_kbps, up_kbps) tuple. cpu: slowdown factor.
    budgets: {"lcp_ms": 2500, "cls": 0.1, ...} (keys from BUDGET_KEYS). Writes <out_base>-perf.json.
    The URL must be on an environment from qa/config.yml. Throttling is reset afterwards.
    """
    preset = NETWORK_PRESETS[network] if isinstance(network, str) else tuple(network)
    cdp("Page.bringToFront")  # background tabs never paint: no FCP/LCP/CLS
    cdp("Network.enable")
    cdp("Performance.enable", timeDomain="timeTicks")
    cdp("Network.setCacheDisabled", cacheDisabled=True)
    if preset:
        lat, down, up = preset
        cdp("Network.emulateNetworkConditions", offline=False, latency=lat,
            downloadThroughput=down * 1000 / 8, uploadThroughput=up * 1000 / 8)
    cdp("Emulation.setCPUThrottlingRate", rate=cpu)
    script_id = cdp("Page.addScriptToEvaluateOnNewDocument", source=_PERF_INIT_JS)["identifier"]
    try:
        cdp("Page.navigate", url=url)
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(0.25)
            try:
                if _eval("document.readyState === 'complete' && performance.getEntriesByType('navigation')[0]?.loadEventEnd > 0", 5):
                    break
            except Exception:
                pass  # page still navigating
        else:
            raise RuntimeError(f"page did not finish loading within {timeout}s under {network} / cpu x{cpu}")
        time.sleep(settle)  # let late LCP candidates and layout shifts arrive
        if _eval("document.visibilityState") != "visible":
            raise RuntimeError("tab is hidden, paint metrics are not recorded; close other tabs and retry")
        m = _eval(_PERF_READ_JS, 30)
        metrics = {x["name"]: x["value"] for x in cdp("Performance.getMetrics")["metrics"]}
        m["cdp"] = {k: metrics.get(k) for k in ("Nodes", "JSHeapUsedSize", "LayoutCount", "RecalcStyleCount",
                                                 "ScriptDuration", "TaskDuration", "LayoutDuration", "Documents", "Frames")}
    finally:
        cdp("Page.removeScriptToEvaluateOnNewDocument", identifier=script_id)
        cdp("Emulation.setCPUThrottlingRate", rate=1)
        cdp("Network.emulateNetworkConditions", offline=False, latency=0, downloadThroughput=-1, uploadThroughput=-1)
        cdp("Network.setCacheDisabled", cacheDisabled=False)
    checks = []
    for k, limit in (budgets or {}).items():
        if k not in BUDGET_KEYS:
            raise ValueError(f"unknown budget '{k}'; use {sorted(BUDGET_KEYS)}")
        val = m.get(BUDGET_KEYS[k])
        checks.append({"budget": k, "limit": limit, "actual": val,
                       "result": "n/a" if val is None else ("PASS" if val <= limit else "FAIL")})
    m["throttling"] = {"network": network, "cpu": cpu}
    m["budgets"] = checks
    raw = _write_json(out_base + "-perf.json", m)
    keep = ("url", "ttfb_ms", "fcp_ms", "lcp_ms", "lcp_element", "cls", "tbt_ms", "load_ms", "requests", "transfer_kb")
    return {**{k: m.get(k) for k in keep}, "throttling": m["throttling"], "budgets": checks,
            "slowest": m["slowest"][:3], "raw": raw}


def qa_cookies(out_base):
    """Flags of every cookie the browser holds for the current page (after login). Writes <out_base>-cookies.json."""
    url = page_info().get("url")
    cookies = cdp("Network.getCookies", urls=[url])["cookies"]
    rows = []
    for c in cookies:
        issues = []
        if not c.get("secure") and url.startswith("https"):
            issues.append("no Secure")
        if not c.get("httpOnly"):
            issues.append("no HttpOnly (readable by JS; fine only for non-session cookies)")
        if not c.get("sameSite"):
            issues.append("no SameSite")
        rows.append({"name": c["name"], "domain": c["domain"], "path": c["path"], "secure": c.get("secure"),
                     "httpOnly": c.get("httpOnly"), "sameSite": c.get("sameSite"),
                     "expires": c.get("expires"), "session": c.get("session"), "issues": issues})
    raw = _write_json(out_base + "-cookies.json", {"url": url, "cookies": rows})  # values are never stored
    return {"url": url, "cookies": len(rows), "with_issues": [r for r in rows if r["issues"]], "raw": raw}


if __name__ == "__main__" and "cdp" not in globals():  # run directly, not exec'd in a browser-use snippet
    import sys
    print(__doc__)
    sys.exit(0 if "--help" in sys.argv or "-h" in sys.argv else 2)
