#!/usr/bin/env python3
"""Build qa/automation/coverage.md: every test case of the selected runs -> spec:line and automation status.

    python3 coverage.py [--run RUN_ID ...] [--manual RUN_ID:TC_ID=reason ...] [--root .] [--check]

Reads (from the project root):
  qa/runs/<RUN_ID>/cases/*.md      TC ids, titles, priorities
  qa/runs/<RUN_ID>/results/*.md    manual result (PASS/FAIL/BLOCKED/SKIPPED) and bug ids
  qa/automation/tests/**/*.spec.ts test titles starting with a TC id (Spec column is relative to qa/automation). The run of a spec file is the
                                   `// testkit-run: <RUN_ID>` comment in its first 5 lines, else its folder name.
  qa/automation/coverage.md        (if present) keeps the reasons of manual-only rows between runs

Status per case:
  automated     a test titled "<TC id> ..." exists (test.fail = known bug, noted with its BUG id)
  manual-only   not automated on purpose; the reason is required (--manual or kept from coverage.md)
  pending       eligible (PASS, or FAIL with a bug) but no spec yet, or the spec uses test.fixme/test.skip
  not-eligible  BLOCKED, SKIPPED, not executed, or FAIL without a bug

Runs: --run (repeatable); default = every run named in spec files or in the existing coverage.md.
--check exits 1 when a spec references a TC id that is not in the cases (stale or mistyped title).
Stdlib only.
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

TC_RE = re.compile(r"TC-[A-Za-z0-9]+-\d+")
CASE_HEAD = re.compile(r"^###\s+(TC-[A-Za-z0-9]+-\d+)\s*[—–-]+\s*(.+?)\s*$")
TEST_DECL = re.compile(r"""\btest(?:\.(only|fail|fixme|skip|slow))?\(\s*['"`](TC-[A-Za-z0-9]+-\d+)""", re.S)
BUG_RE = re.compile(r"BUG-[A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9]")
RUN_HDR = re.compile(r"testkit-run:\s*([A-Za-z0-9._-]+)")


def die(msg):
    print(f"coverage: {msg}", file=sys.stderr)
    sys.exit(2)


def read_cases(run_dir):
    cases = {}
    for f in sorted((run_dir / "cases").glob("*.md")):
        cur = None
        for line in f.read_text(encoding="utf-8").splitlines():
            m = CASE_HEAD.match(line)
            if m:
                cur = m.group(1)
                cases[cur] = {"title": m.group(2), "priority": "", "stream": f.stem}
                continue
            if cur:
                pm = re.match(r"^\s*-\s*Priority:\s*(P\d)", line)
                if pm:
                    cases[cur]["priority"] = pm.group(1)
    return cases


def table_rows(text):
    """Yield dicts for markdown table rows, keyed by lower-cased header."""
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


def read_results(run_dir):
    res = {}
    for f in sorted((run_dir / "results").glob("*.md")):
        for row in table_rows(f.read_text(encoding="utf-8")):
            tc = TC_RE.search(row.get("case", ""))
            if tc:
                res[tc.group(0)] = {"status": row.get("status", "").upper(), "bug": " ".join(BUG_RE.findall(row.get("bug", "")))}
    return res


def scan_specs(tests_dir, base):
    found = {}  # (run, tc) -> list of {loc, kind, bugs}
    for f in sorted(tests_dir.rglob("*.spec.ts")):
        text = f.read_text(encoding="utf-8")
        lines = text.splitlines()
        run = next((m.group(1) for l in lines[:5] if (m := RUN_HDR.search(l))), f.parent.name)
        for m in TEST_DECL.finditer(text):  # the title may sit on the line after `test.fail(`
            line_no = text.count("\n", 0, m.start(2)) + 1
            window = "\n".join(lines[line_no - 2:line_no + 12])
            kind = m.group(1) or "test"
            if kind == "test" and re.search(r"\btest\.fail\(", window):
                kind = "fail"
            found.setdefault((run, m.group(2)), []).append({
                "loc": f"{f.relative_to(base).as_posix()}:{line_no}", "kind": kind,
                "bugs": sorted(set(BUG_RE.findall(window)))})
    return found


def read_existing(cov_file):
    keep = {}
    if not cov_file.exists():
        return keep
    for row in table_rows(cov_file.read_text(encoding="utf-8")):
        if row.get("status") == "manual-only" and row.get("tc"):
            keep[(row.get("run", ""), row["tc"])] = row.get("reason / notes", "")
    return keep


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--run", action="append", default=[], help="RUN_ID to include (repeatable)")
    ap.add_argument("--manual", action="append", default=[], help="RUN_ID:TC_ID=reason (repeatable)")
    ap.add_argument("--root", default=".")
    ap.add_argument("--dir", default="qa/automation", help="suite folder (default qa/automation)")
    ap.add_argument("--check", action="store_true", help="exit 1 if specs reference unknown TC ids")
    a = ap.parse_args()

    root = Path(a.root).resolve()
    auto = root / a.dir
    if not (auto / "tests").is_dir():
        die(f"{auto / 'tests'} not found")
    cov_file = auto / "coverage.md"
    specs = scan_specs(auto / "tests", auto)
    manual = read_existing(cov_file)
    for item in a.manual:
        m = re.match(r"^(?:([^:]+):)?(TC-[A-Za-z0-9]+-\d+)=(.+)$", item)
        if not m:
            die(f"--manual expects RUN_ID:TC_ID=reason, got {item!r}")
        run = m.group(1) or (a.run[0] if len(a.run) == 1 else None)
        if not run:
            die(f"--manual {item!r}: prefix the RUN_ID when several runs are selected")
        manual[(run, m.group(2))] = m.group(3).strip()

    runs = a.run or sorted({r for r, _ in specs} | {r for r, _ in manual})
    if not runs:
        die("no runs selected: pass --run RUN_ID")

    rows, unknown, counts = [], [], {"automated": 0, "manual-only": 0, "pending": 0, "not-eligible": 0}
    for run in runs:
        run_dir = root / "qa" / "runs" / run
        if not run_dir.is_dir():
            die(f"{run_dir} not found")
        cases, results = read_cases(run_dir), read_results(run_dir)
        for (r, tc), hits in specs.items():
            if r == run and tc not in cases:
                unknown.append(f"{run} {tc} ({hits[0]['loc']})")
        for tc, c in cases.items():
            res = results.get(tc, {"status": "", "bug": ""})
            hits = specs.get((run, tc), [])
            live = [h for h in hits if h["kind"] not in ("fixme", "skip")]
            locs = "<br>".join(h["loc"] for h in hits)
            if live:
                status = "automated"
                bugs = sorted({b for h in live if h["kind"] == "fail" for b in h["bugs"]})
                note = f"known bug {', '.join(bugs) or '(no BUG id!)'} (test.fail)" if any(h["kind"] == "fail" for h in live) else ""
            elif hits:
                status, note = "pending", "test.fixme/test.skip in spec"
            elif (run, tc) in manual:
                status, note = "manual-only", manual[(run, tc)] or "(reason missing)"
            elif res["status"] == "PASS" or (res["status"] == "FAIL" and res["bug"]):
                status = "pending"
                note = "not generated yet" + (f"; known bug {res['bug']}" if res["status"] == "FAIL" else "")
            else:
                status = "not-eligible"
                note = {"": "not executed", "FAIL": "FAIL without a bug id"}.get(res["status"], res["status"])
            counts[status] += 1
            rows.append([run, tc, c["title"].replace("|", "\\|"), c["priority"], res["status"] or "—", status, locs, note])

    total = len(rows)
    eligible = total - counts["not-eligible"]
    pct = f"{100 * counts['automated'] / eligible:.0f}%" if eligible else "n/a"
    out = [
        "# Automation coverage",
        "",
        f"Generated by testkit-automate `coverage.py` on {dt.date.today().isoformat()} for runs: {', '.join(runs)}. "
        "Re-run it after every change to the specs. Only the reason of `manual-only` rows is kept between runs.",
        "",
        f"Summary: {total} cases · automated {counts['automated']} ({pct} of {eligible} eligible) · "
        f"manual-only {counts['manual-only']} · pending {counts['pending']} · not-eligible {counts['not-eligible']}",
        "",
        "| Run | TC | Title | Priority | Manual result | Status | Spec | Reason / notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    if unknown:
        out += ["", "## Specs referencing unknown cases", ""] + [f"- {u}" for u in unknown]
    cov_file.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {cov_file.relative_to(root)}: {out[4]}")
    for u in unknown:
        print(f"warning: spec references unknown case {u}", file=sys.stderr)
    if a.check and unknown:
        sys.exit(1)


if __name__ == "__main__":
    main()
