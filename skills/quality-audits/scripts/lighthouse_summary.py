#!/usr/bin/env python3
"""Summarise a Lighthouse JSON report and check it against budgets (stdlib only).

    python3 lighthouse_summary.py REPORT.json [--budget lcp_ms=2500] [--budget cls=0.1]
                                  [--min-score performance=0.8] [--json OUT.json]

Prints category scores, lab metrics, failing audits (worst first) and a budget table.
Budget keys: fcp_ms lcp_ms cls tbt_ms si_ms tti_ms ttfb_ms transfer_kb requests.
Exit codes: 0 all budgets and min scores met, 1 at least one missed, 2 usage or input error.
"""
import argparse
import json
import sys

METRICS = {  # budget key -> (lighthouse audit id, factor applied to numericValue)
    "fcp_ms": ("first-contentful-paint", 1),
    "lcp_ms": ("largest-contentful-paint", 1),
    "cls": ("cumulative-layout-shift", 1),
    "tbt_ms": ("total-blocking-time", 1),
    "si_ms": ("speed-index", 1),
    "tti_ms": ("interactive", 1),
    "ttfb_ms": ("server-response-time", 1),
    "transfer_kb": ("total-byte-weight", 1 / 1024),
    "requests": ("network-requests", None),
}


def kv(s):
    if "=" not in s:
        raise argparse.ArgumentTypeError(f"expected key=value, got '{s}'")
    k, v = s.split("=", 1)
    try:
        return k.strip(), float(v)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{v}' is not a number")


def metric(report, key):
    audit_id, factor = METRICS[key]
    a = report["audits"].get(audit_id) or {}
    if factor is None:  # count items
        items = (a.get("details") or {}).get("items")
        return len(items) if items is not None else None
    v = a.get("numericValue")
    return None if v is None else (round(v, 4) if key == "cls" else int(round(v * factor)))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("report", help="Lighthouse JSON (…report.json)")
    p.add_argument("--budget", action="append", type=kv, default=[], help="metric budget, e.g. lcp_ms=2500")
    p.add_argument("--min-score", action="append", type=kv, default=[], help="category minimum 0-1, e.g. performance=0.8")
    p.add_argument("--json", help="also write the summary as JSON here")
    a = p.parse_args()
    try:
        r = json.load(open(a.report, encoding="utf-8"))
        r["audits"], r["categories"]
    except (OSError, ValueError, KeyError) as e:
        print(f"lighthouse_summary: cannot read a Lighthouse report from {a.report}: {e}", file=sys.stderr)
        return 2
    if r.get("runtimeError"):
        print(f"lighthouse_summary: the run failed: {r['runtimeError']}", file=sys.stderr)
        return 2
    for k, _ in a.budget:
        if k not in METRICS:
            print(f"lighthouse_summary: unknown budget '{k}' (use {', '.join(METRICS)})", file=sys.stderr)
            return 2

    cs = r.get("configSettings", {})
    scores = {k: c.get("score") for k, c in r["categories"].items()}
    metrics = {k: metric(r, k) for k in METRICS}
    failing = []
    for cid, cat in r["categories"].items():
        for ref in cat["auditRefs"]:
            au = r["audits"].get(ref["id"], {})
            if ref.get("group") == "metrics" or au.get("score") is None or au["score"] >= 0.9:
                continue
            if au.get("scoreDisplayMode") in ("manual", "notApplicable", "informative"):
                continue
            savings = sum((au.get("metricSavings") or {}).values())
            failing.append({"category": cid, "id": au["id"], "title": au.get("title"), "score": au["score"],
                            "display": au.get("displayValue", ""), "savings": savings, "weight": ref.get("weight", 0)})
    failing.sort(key=lambda x: (-x["savings"], -x["weight"], x["score"]))
    checks = []
    for k, limit in a.budget:
        v = metrics[k]
        checks.append({"budget": k, "limit": limit, "actual": v, "result": "n/a" if v is None else ("PASS" if v <= limit else "FAIL")})
    for k, limit in a.min_score:
        v = scores.get(k)
        checks.append({"budget": f"score.{k}", "limit": limit, "actual": v,
                       "result": "n/a" if v is None else ("PASS" if v >= limit else "FAIL")})

    out = {"url": r.get("finalDisplayedUrl") or r.get("finalUrl"), "lighthouse": r.get("lighthouseVersion"),
           "form_factor": cs.get("formFactor"), "throttling": cs.get("throttlingMethod"), "scores": scores,
           "metrics": metrics, "failing_audits": failing, "budgets": checks}
    print(f"# Lighthouse {out['lighthouse']} — {out['url']} ({out['form_factor']}, {out['throttling']})\n")
    print("| Category | Score |\n|---|---|")
    for k, v in scores.items():
        print(f"| {k} | {'n/a' if v is None else round(v * 100)} |")
    print("\n| Metric | Value |\n|---|---|")
    for k, v in metrics.items():
        print(f"| {k} | {'n/a' if v is None else v} |")
    if checks:
        print("\n| Budget | Limit | Actual | Result |\n|---|---|---|---|")
        for c in checks:
            print(f"| {c['budget']} | {c['limit']:g} | {c['actual']} | {c['result']} |")
    if failing:
        print("\n| Failing audit | Category | Score | Detail |\n|---|---|---|---|")
        for f in failing[:15]:
            print(f"| {f['id']} | {f['category']} | {f['score']} | {f['display']} |")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, ensure_ascii=False)
    return 1 if any(c["result"] == "FAIL" for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
