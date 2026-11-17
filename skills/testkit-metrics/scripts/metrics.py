#!/usr/bin/env python3
"""Quality metrics across testkit runs and bugs, as JSON.

    python3 metrics.py --from 2026-11-01 --to 2026-11-15 [--out metrics.json]
    python3 metrics.py --runs PROJ-123 PROJ-130 [--out metrics.json]
    python3 metrics.py --all

Options: --root <project root> (default .), --today YYYY-MM-DD (aging reference, default today).

Reads (from the project root):
  qa/runs/<RUN_ID>/plan.md       title, ticket, created date, acceptance criteria, stream titles
  qa/runs/<RUN_ID>/cases/*.md    planned cases (### TC-…), priority, Requirement (AC ids), traceability tables
  qa/runs/<RUN_ID>/results/*.md  PASS/FAIL/BLOCKED/SKIPPED per case, "Executed: <date>"
  qa/runs/<RUN_ID>/report.md     verdict (READY | READY WITH KNOWN ISSUES | NOT READY)
  qa/bugs/*.md                   frontmatter (id, status, severity, ticket, test_case, component, found_at)
                                 and "## History" lines "- YYYY-MM-DD <status> — …"
  qa/automation/coverage.md      (optional) automation status per case

Run date = first "Executed:" date in results, else plan "Created:", else report.md mtime.
A run is selected when its date is inside --from/--to (inclusive) or its id is in --runs.
A bug is selected when its ticket (or the RUN_ID in its id) belongs to a selected run.
Stdlib only. Exit 1 when nothing matches the selection.
"""
import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
TC_RE = re.compile(r"TC-[A-Za-z0-9]+-\d+")
AC_RE = re.compile(r"\bAC-\d+\b")
CASE_HEAD = re.compile(r"^###\s+(TC-[A-Za-z0-9]+-\d+)\s*[—–-]+\s*(.+?)\s*$")
HIST = re.compile(r"^\s*-\s*(\d{4}-\d{2}-\d{2})\s+([a-z_]+)\b")
STATUSES = ("PASS", "FAIL", "BLOCKED", "SKIPPED")
SEVERITIES = ("blocker", "critical", "major", "minor", "trivial")
SEV_WEIGHT = {"blocker": 8, "critical": 5, "major": 3, "minor": 1, "trivial": 0.5}
CLOSED = {"verified", "wont_fix", "duplicate"}
AGING = [(2, "0-2d"), (7, "3-7d"), (14, "8-14d"), (30, "15-30d"), (10**6, ">30d")]


def die(msg, code=2):
    print(f"metrics: {msg}", file=sys.stderr)
    sys.exit(code)


def parse_date(s):
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def table_rows(text):
    header = None
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        yield dict(zip(header, cells))


def section(text, title):
    m = re.search(rf"^##\s+{re.escape(title)}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S | re.I)
    return m.group(1) if m else ""


def pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def read_run(run_dir):
    rid = run_dir.name
    plan = (run_dir / "plan.md").read_text(encoding="utf-8") if (run_dir / "plan.md").exists() else ""
    title = re.search(r"^#\s+.*?—\s*(?:[^:]+:\s*)?(.+)$", plan, re.M)
    ticket = re.search(r"^-\s*Ticket:\s*(\S+)", plan, re.M)
    created = re.search(r"^-\s*Created:\s*(\d{4}-\d{2}-\d{2})", plan, re.M)
    acs = {}
    for line in section(plan, "Acceptance criteria").splitlines():
        m = re.match(r"^\s*-\s*(AC-\d+)\s*[:.]?\s*(.*)$", line)
        if m:
            acs[m.group(1)] = m.group(2).strip()
    stream_titles = {}
    for row in table_rows(section(plan, "Streams")):
        if row.get("id"):
            stream_titles[row["id"]] = row.get("title", "")

    cases, ac_cases = {}, defaultdict(set)
    for f in sorted((run_dir / "cases").glob("*.md")):
        text = f.read_text(encoding="utf-8")
        cur = None
        for line in text.splitlines():
            m = CASE_HEAD.match(line)
            if m:
                cur = m.group(1)
                cases[cur] = {"stream": f.stem, "title": m.group(2), "priority": "", "acs": []}
                continue
            if cur:
                pm = re.match(r"^\s*-\s*Priority:\s*(P\d)", line)
                if pm:
                    cases[cur]["priority"] = pm.group(1)
                rm = re.match(r"^\s*-\s*Requirement:\s*(.+)$", line)
                if rm:
                    cases[cur]["acs"] = AC_RE.findall(rm.group(1))
                    for ac in cases[cur]["acs"]:
                        ac_cases[ac].add(cur)
        for row in table_rows(section(text, "Traceability")):
            for ac in AC_RE.findall(row.get("requirement", "")):
                ac_cases[ac].update(TC_RE.findall(row.get("test cases", "")))
        stream_titles.setdefault(f.stem, re.sub(r"^#\s*\S+\s*[—–-]\s*", "", text.splitlines()[0]) if text else f.stem)

    results, exec_dates = {}, []
    for f in sorted((run_dir / "results").glob("*.md")):
        text = f.read_text(encoding="utf-8")
        m = re.search(r"Executed:\s*(\d{4}-\d{2}-\d{2})", text)
        if m:
            exec_dates.append(m.group(1))
        for row in table_rows(text):
            tc = TC_RE.search(row.get("case", ""))
            st = row.get("status", "").strip().upper()
            if tc and st in STATUSES:
                results[tc.group(0)] = {"status": st, "stream": f.stem}

    report = run_dir / "report.md"
    verdict = None
    if report.exists():
        rt = report.read_text(encoding="utf-8").upper()
        for v in ("READY WITH KNOWN ISSUES", "NOT READY", "READY"):
            if v in rt:
                verdict = v
                break
    date = min(exec_dates) if exec_dates else (created.group(1) if created else None)
    if not date and report.exists():
        date = dt.date.fromtimestamp(report.stat().st_mtime).isoformat()
    return {"id": rid, "ticket": ticket.group(1) if ticket else rid, "title": title.group(1).strip() if title else rid,
            "date": date, "verdict": verdict, "acs": acs, "ac_cases": ac_cases, "cases": cases,
            "results": results, "stream_titles": stream_titles}


def read_bug(f):
    text = f.read_text(encoding="utf-8")
    fm = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            km = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
            if km:
                v = re.sub(r"\s+#.*$", "", km.group(2)).strip().strip("'\"")
                fm[km.group(1)] = v
    hist = []
    for line in section(text, "History").splitlines():
        hm = HIST.match(line)
        if hm:
            hist.append((hm.group(1), hm.group(2)))
    fm.setdefault("id", f.stem)
    fm["history"] = hist
    return fm


def cycle_days(hist, start_states, end_state, latest=False, resets=()):
    """Days from a start_state event to the next end_state event, for every cycle in the history.
    latest=True measures from the most recent start event (fixed -> verified after a re-fix);
    a status in `resets` cancels the pending start (reopened cancels a fixed)."""
    out, start = [], None
    for d, st in hist:
        if st in start_states and (start is None or latest):
            start = d
        elif st in resets:
            start = None
        elif st == end_state and start is not None:
            a, b = parse_date(start), parse_date(d)
            if a and b:
                out.append((b - a).days)
            start = None
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--from", dest="date_from")
    ap.add_argument("--to", dest="date_to")
    ap.add_argument("--runs", nargs="+", default=[])
    ap.add_argument("--all", action="store_true", help="every run")
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--out", help="write JSON here (default: stdout)")
    a = ap.parse_args()
    if not (a.runs or a.all or a.date_from or a.date_to):
        die("choose runs: --from/--to, --runs or --all")
    today = parse_date(a.today) or die(f"bad --today {a.today}")
    d_from, d_to = parse_date(a.date_from) if a.date_from else None, parse_date(a.date_to) if a.date_to else None
    if (a.date_from and not d_from) or (a.date_to and not d_to):
        die("dates must be YYYY-MM-DD")

    root = Path(a.root).resolve()
    runs_dir = root / "qa" / "runs"
    if not runs_dir.is_dir():
        die(f"{runs_dir} not found (run from the project root)")
    warnings = []
    runs = []
    for d in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        if a.runs and d.name not in a.runs:
            continue
        r = read_run(d)
        if not a.runs and not a.all:
            rd = parse_date(r["date"])
            if not rd or (d_from and rd < d_from) or (d_to and rd > d_to):
                continue
        runs.append(r)
    for rid in a.runs:
        if not any(r["id"] == rid for r in runs):
            warnings.append(f"run {rid} not found in qa/runs")
    if not runs:
        die("no run matches the selection", 1)

    # ---- cases, results, ACs
    tot = Counter()
    run_out, ac_tot = [], Counter()
    for r in sorted(runs, key=lambda r: (r["date"] or "", r["id"])):
        c = Counter(v["status"] for v in r["results"].values())
        planned = len(r["cases"])
        not_run = len([tc for tc in r["cases"] if tc not in r["results"]])
        executed = c["PASS"] + c["FAIL"]
        acs_out = []
        for ac, text in r["acs"].items():
            tcs = sorted(r["ac_cases"].get(ac, set()))
            sts = [r["results"].get(tc, {}).get("status") for tc in tcs]
            if not tcs:
                status = "NOT COVERED"
            elif "FAIL" in sts:
                status = "FAIL"
            elif sts and all(s == "PASS" for s in sts):
                status = "PASS"
            elif any(s == "PASS" for s in sts):
                status = "PARTIAL"
            else:
                status = "NOT RUN"
            acs_out.append({"id": ac, "text": text, "cases": tcs, "status": status})
            ac_tot["total"] += 1
            ac_tot["covered"] += bool(tcs)
            ac_tot["executed"] += any(s in ("PASS", "FAIL") for s in sts)
            ac_tot["passed"] += status == "PASS"
        streams = sorted({v["stream"] for v in r["cases"].values()})
        run_out.append({
            "id": r["id"], "ticket": r["ticket"], "title": r["title"], "date": r["date"], "verdict": r["verdict"],
            "streams": len(streams), "planned": planned, "executed": executed,
            "pass": c["PASS"], "fail": c["FAIL"], "blocked": c["BLOCKED"], "skipped": c["SKIPPED"], "not_run": not_run,
            "pass_rate": pct(c["PASS"], executed), "acs": acs_out})
        tot.update({"runs": 1, "streams": len(streams), "planned": planned, "executed": executed, "pass": c["PASS"],
                    "fail": c["FAIL"], "blocked": c["BLOCKED"], "skipped": c["SKIPPED"], "not_run": not_run})
        if not r["acs"]:
            warnings.append(f"{r['id']}: no acceptance criteria found in plan.md")
        if not r["results"]:
            warnings.append(f"{r['id']}: no results yet")

    # ---- bugs
    run_by_ticket = {r["ticket"]: r for r in runs}
    run_ids = {r["id"]: r for r in runs}
    bugs = []
    bugs_dir = root / "qa" / "bugs"
    for f in sorted(bugs_dir.glob("*.md")) if bugs_dir.is_dir() else []:
        if f.name.lower() == "index.md":
            continue
        b = read_bug(f)
        run = run_by_ticket.get(b.get("ticket")) or next(
            (r for rid, r in run_ids.items() if b["id"].startswith(f"BUG-{rid}-")), None)
        if not run:
            continue
        b["run"] = run["id"]
        tc = b.get("test_case", "")
        stream = run["cases"].get(tc, {}).get("stream") or (re.match(r"TC-([A-Za-z0-9]+)-", tc) or [None, None])[1]
        b["component"] = b.get("component") or f"{run['id']} {run['stream_titles'].get(stream, stream or '?')}"
        if not b["history"]:
            warnings.append(f"{b['id']}: no History lines; time metrics skip it")
        bugs.append(b)

    live = [b for b in bugs if b.get("status") != "duplicate"]
    by_sev = Counter(b.get("severity", "?") for b in live)
    by_status = Counter(b.get("status", "?") for b in bugs)
    by_ticket = Counter(b.get("ticket") or b["run"] for b in live)
    by_comp = Counter(b["component"] for b in live)
    fix_days = [d for b in live for d in cycle_days(b["history"], {"open", "reopened"}, "fixed")]
    verify_days = [d for b in live for d in cycle_days(b["history"], {"fixed"}, "verified", latest=True, resets={"reopened"})]
    ever_fixed = [b for b in live if any(s == "fixed" for _, s in b["history"])]
    reopened = [b for b in live if any(s == "reopened" for _, s in b["history"])]
    open_bugs, aging = [], Counter({label: 0 for _, label in AGING})
    for b in live:
        if b.get("status") in CLOSED:
            continue
        start = parse_date(b.get("found_at")) or (parse_date(b["history"][0][0]) if b["history"] else None)
        age = (today - start).days if start else None
        if age is not None:
            aging[next(label for lim, label in AGING if age <= lim)] += 1
        open_bugs.append({"id": b["id"], "title": b.get("title", ""), "severity": b.get("severity", ""),
                          "status": b.get("status", ""), "ticket": b.get("ticket", ""), "age_days": age})
    open_bugs.sort(key=lambda x: (SEVERITIES.index(x["severity"]) if x["severity"] in SEVERITIES else 9, -(x["age_days"] or 0)))
    density = []
    for r in run_out:
        n = by_ticket.get(r["ticket"], 0)
        density.append({"ticket": r["ticket"], "run": r["id"], "bugs": n, "executed": r["executed"],
                        "acs": len(r["acs"]), "bugs_per_10_cases": round(10 * n / r["executed"], 2) if r["executed"] else None,
                        "bugs_per_ac": round(n / len(r["acs"]), 2) if r["acs"] else None})

    # ---- automation coverage
    automation = {"present": False}
    cov = root / "qa" / "automation" / "coverage.md"
    if cov.exists():
        c = Counter()
        for row in table_rows(cov.read_text(encoding="utf-8")):
            if row.get("run") in run_ids and row.get("status"):
                c[row["status"]] += 1
        eligible = sum(c.values()) - c["not-eligible"]
        automation = {"present": True, "cases": sum(c.values()), "automated": c["automated"],
                      "manual_only": c["manual-only"], "pending": c["pending"], "not_eligible": c["not-eligible"],
                      "automated_rate": pct(c["automated"], eligible)}

    # ---- risky areas: severity-weighted bugs (open count fully, closed 30%), reopens, failed/blocked cases
    area = defaultdict(lambda: {"score": 0.0, "bugs": 0, "open_bugs": 0, "reopens": 0, "failed_cases": 0, "blocked_cases": 0})
    for b in live:
        a_ = area[b["component"]]
        w = SEV_WEIGHT.get(b.get("severity"), 1)
        is_open = b.get("status") not in CLOSED
        a_["score"] += w if is_open else 0.3 * w
        a_["bugs"] += 1
        a_["open_bugs"] += is_open
        n_re = sum(1 for _, s in b["history"] if s == "reopened")
        a_["reopens"] += n_re
        a_["score"] += 2 * n_re
    for r in runs:
        for tc, res in r["results"].items():
            st = res["stream"]
            name = f"{r['id']} {r['stream_titles'].get(st, st)}"
            name = next((b["component"] for b in live if b["run"] == r["id"] and
                         r["cases"].get(b.get("test_case", ""), {}).get("stream") == st), name)
            if res["status"] == "FAIL":
                area[name]["failed_cases"] += 1
                area[name]["score"] += 1
            elif res["status"] == "BLOCKED":
                area[name]["blocked_cases"] += 1
                area[name]["score"] += 0.5
    risky = []
    for name, v in sorted(area.items(), key=lambda kv: -kv[1]["score"]):
        if v["score"] <= 0:
            continue
        reasons = []
        if v["open_bugs"]:
            reasons.append(f"{v['open_bugs']} open bug(s)")
        if v["reopens"]:
            reasons.append(f"{v['reopens']} reopen(s)")
        if v["failed_cases"]:
            reasons.append(f"{v['failed_cases']} failed case(s)")
        if v["blocked_cases"]:
            reasons.append(f"{v['blocked_cases']} blocked case(s)")
        risky.append({"area": name, "score": round(v["score"], 1), **{k: v[k] for k in v if k != "score"}, "reasons": reasons})
    risky = risky[:5]

    mean = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    out = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "selection": {"from": a.date_from, "to": a.date_to, "runs": [r["id"] for r in run_out],
                      "mode": "runs" if a.runs else ("all" if a.all else "date range")},
        "totals": {**{k: tot[k] for k in ("runs", "streams", "planned", "executed", "pass", "fail", "blocked", "skipped", "not_run")},
                   "execution_rate": pct(tot["executed"], tot["planned"]), "pass_rate": pct(tot["pass"], tot["executed"]),
                   "fail_rate": pct(tot["fail"], tot["executed"]), "blocked_rate": pct(tot["blocked"], tot["planned"])},
        "ac_coverage": {**{k: ac_tot[k] for k in ("total", "covered", "executed", "passed")},
                        "coverage_rate": pct(ac_tot["covered"], ac_tot["total"]),
                        "pass_rate": pct(ac_tot["passed"], ac_tot["total"])},
        "runs": run_out,
        "defects": {
            "total": len(live), "duplicates": by_status.get("duplicate", 0),
            "by_severity": {s: by_sev.get(s, 0) for s in SEVERITIES},
            "by_status": dict(by_status.most_common()), "by_ticket": dict(by_ticket.most_common()),
            "by_component": dict(by_comp.most_common()), "density": density,
            "reopen_rate": pct(len(reopened), len(ever_fixed)), "reopened_bugs": [b["id"] for b in reopened],
            "mean_days_to_fix": mean(fix_days), "fix_samples": len(fix_days),
            "mean_days_to_verify": mean(verify_days), "verify_samples": len(verify_days),
            "open_aging": dict(aging), "open": open_bugs,
        },
        "automation": automation,
        "risky_areas": risky,
        "warnings": warnings,
    }
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text + "\n", encoding="utf-8")
        t = out["totals"]
        print(f"wrote {a.out}: {t['runs']} runs, {t['planned']} cases, pass rate {t['pass_rate']}%, "
              f"{len(live)} bugs ({len(open_bugs)} open)")
    else:
        print(text)


if __name__ == "__main__":
    main()
