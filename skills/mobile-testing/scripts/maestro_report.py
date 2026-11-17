#!/usr/bin/env python3
"""Turn a Maestro run into testkit evidence and result rows (stdlib only).

    python3 maestro_report.py --junit qa/runs/R/results/S-maestro.xml \
        --artifacts qa/runs/R/evidence/S/maestro --evidence qa/runs/R/evidence/S [--json OUT.json]

1. Redacts secrets: every value of an environment variable whose name starts with MAESTRO_ or is
   listed in --secret-env (6+ characters) is replaced by {{redacted:NAME}} in the text artifacts
   (commands.json, logs, report XML). Maestro writes typed input in clear text there.
2. Copies screenshots next to the browser evidence: takeScreenshot/<name>.png -> <evidence>/<name>.png,
   the automatic failure screenshot -> <evidence>/<TC_ID>-fail.png.
3. Prints one markdown row per flow: | Case | Status | Evidence | Notes |  (PASS / FAIL / BLOCKED).

The case ID is the flow file name (<TC_ID>.yaml) or the first word of the flow `name:`.
Exit codes: 0 all flows passed, 1 at least one failed, 2 usage or input error.
"""
import argparse
import json
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TEXT_EXT = {".json", ".log", ".txt", ".xml", ".html"}
TC_RE = re.compile(r"TC-[A-Za-z0-9]+-\d+")


def secrets(extra):
    out = {}
    for k, v in os.environ.items():
        if (k.startswith("MAESTRO_") and not k.startswith("MAESTRO_CLI_")) or k in extra:
            if v and len(v) >= 6:
                out[k] = v
    return out


def redact(paths, secret_map):
    hits = 0
    for p in paths:
        try:
            t = p.read_text(encoding="utf-8", errors="surrogateescape")
        except OSError:
            continue
        new = t
        for k, v in sorted(secret_map.items(), key=lambda kv: -len(kv[1])):
            for form in {v, json.dumps(v)[1:-1]}:
                new = new.replace(form, "{{redacted:%s}}" % k)
        if new != t:
            p.write_text(new, encoding="utf-8", errors="surrogateescape")
            hits += 1
    return hits


def case_id(tc):
    for s in (Path(tc.get("file") or "").stem, tc.get("name") or ""):
        m = TC_RE.search(s)
        if m:
            return m.group(0)
    return (tc.get("name") or "?").split()[0]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__.split("\n\n", 1)[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--junit", required=True, help="report written by maestro test --format junit --output")
    p.add_argument("--artifacts", required=True, help="the --test-output-dir of the run")
    p.add_argument("--evidence", required=True, help="stream evidence folder to copy screenshots into")
    p.add_argument("--secret-env", action="append", default=[], help="extra env var whose value must be redacted")
    p.add_argument("--json", help="write the rows as JSON too")
    a = p.parse_args()

    junit, art, ev = Path(a.junit), Path(a.artifacts), Path(a.evidence)
    if not junit.is_file():
        print(f"maestro_report: JUnit report not found: {junit} (did maestro test run with --format junit --output?)",
              file=sys.stderr)
        return 2
    smap = secrets(set(a.secret_env))
    text_files = [f for f in art.rglob("*") if f.is_file() and f.suffix.lower() in TEXT_EXT] if art.is_dir() else []
    redacted = redact(text_files + [junit], smap)
    try:
        root = ET.parse(junit).getroot()
    except ET.ParseError as e:
        print(f"maestro_report: cannot parse {junit}: {e}", file=sys.stderr)
        return 2

    ev.mkdir(parents=True, exist_ok=True)
    # artifacts/<timestamp>/<flow name>/... ; newest timestamp wins when a flow ran twice
    flow_dirs = {}
    if art.is_dir():
        for d in sorted(art.glob("*/*")):
            if d.is_dir():
                flow_dirs[d.name] = d
    rows = []
    for suite in root.iter("testsuite"):
        device = suite.get("device", "")
        for tc in suite.iter("testcase"):
            cid = case_id(tc)
            status = {"SUCCESS": "PASS", "ERROR": "FAIL", "FAILURE": "FAIL", "SKIPPED": "BLOCKED"}.get(
                (tc.get("status") or "").upper(), "FAIL" if tc.find("failure") is not None else "PASS")
            note = ""
            f = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
            if f is not None:
                note = (f.text or f.get("message") or "").strip().splitlines()[0][:200]
            shots = []
            d = flow_dirs.get(tc.get("name") or "")
            if d:
                for s in sorted((d / "takeScreenshot").glob("*.png")):
                    dst = ev / s.name
                    shutil.copyfile(s, dst)
                    shots.append(dst.as_posix())
                fails = sorted((d / "screenshots").glob("*.png"))
                if status == "FAIL" and fails:
                    dst = ev / f"{cid}-fail.png"
                    shutil.copyfile(fails[-1], dst)
                    shots.append(dst.as_posix())
            rows.append({"case": cid, "status": status, "evidence": shots, "notes": note,
                         "time_s": tc.get("time"), "device": device, "flow": tc.get("file")})

    print(f"<!-- maestro: {len(rows)} flows, device {rows[0]['device'] if rows else '?'}; "
          f"secrets redacted in {redacted} file(s) -->")
    print("| Case | Status | Evidence | Notes |\n|---|---|---|---|")
    for r in rows:
        print(f"| {r['case']} | {r['status']} | {'<br>'.join(r['evidence'])} | {r['notes']} |")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 1 if any(r["status"] == "FAIL" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
