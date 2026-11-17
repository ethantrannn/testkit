# /// script
# requires-python = ">=3.10"
# dependencies = ["openpyxl==3.1.5"]
# ///
"""Read a filled UAT workbook (made by testkit-uat) and summarise the results.

    uv run read_uat_results.py qa/uat/<UAT_ID>/<UAT_ID>-uat-filled.xlsx [--json out.json]

Looks for the sheet "UAT" (else the first sheet that has scenario rows). A scenario row is a row
whose column A looks like UAT-<n>. Columns by position: A Scenario ID, B Business flow,
C Preconditions, D Steps, E Expected result, F Result, G Comment, H Tester, I Date.
Also reads the "Defects" sheet if present (A Defect ID, B Scenario ID, C Description,
D Severity, E Status), skipping empty rows.

Prints a markdown summary (totals, failed and not-run scenarios with comments, defects) and,
with --json, writes the parsed rows. Exit 1 if the file cannot be read or has no scenarios.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from openpyxl import load_workbook

SCENARIO_RE = re.compile(r"^UAT-\d+", re.I)
COLS = ["id", "flow", "preconditions", "steps", "expected", "result", "comment", "tester", "date"]
DEFECT_COLS = ["id", "scenario", "description", "severity", "status"]


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def text(v):
    if v is None:
        return ""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", s)  # dd/mm/yyyy (vi) → ISO
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else s


def norm_result(v):
    s = text(v).lower()
    if s in ("pass", "passed", "đạt", "ok"):
        return "Pass"
    if s in ("fail", "failed", "không đạt", "khong dat"):
        return "Fail"
    return "" if not s else text(v)  # unknown value kept as written


def scenarios_of(ws):
    out = []
    for row in ws.iter_rows(values_only=True):
        if row and SCENARIO_RE.match(text(row[0])):
            vals = [text(row[i]) if i < len(row) else "" for i in range(len(COLS))]
            rec = dict(zip(COLS, vals))
            rec["result"] = norm_result(row[5] if len(row) > 5 else None)
            out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("workbook")
    ap.add_argument("--json", dest="out_json")
    a = ap.parse_args()
    path = Path(a.workbook)
    if not path.is_file():
        fail(f"not a file: {path}")
    try:
        wb = load_workbook(str(path), data_only=True, read_only=True)
    except Exception as e:  # noqa: BLE001
        fail(f"cannot open {path}: {e}")

    sheets = ([wb["UAT"]] if "UAT" in wb.sheetnames else []) + \
        [ws for ws in wb.worksheets if ws.title != "UAT"]
    scenarios = []
    for ws in sheets:
        scenarios = scenarios_of(ws)
        if scenarios:
            break
    if not scenarios:
        fail("no scenario rows (column A = UAT-<n>) found")

    defects = []
    if "Defects" in wb.sheetnames:
        for row in wb["Defects"].iter_rows(values_only=True):
            vals = [text(row[i]) if row and i < len(row) else "" for i in range(len(DEFECT_COLS))]
            if vals[0] and vals[0].lower() not in ("defect id", "mã lỗi", "id") and any(vals[1:]):
                defects.append(dict(zip(DEFECT_COLS, vals)))

    n = len(scenarios)
    passed = sum(s["result"] == "Pass" for s in scenarios)
    failed = sum(s["result"] == "Fail" for s in scenarios)
    not_run = [s for s in scenarios if not s["result"]]
    odd = [s for s in scenarios if s["result"] not in ("Pass", "Fail", "")]
    print(f"# UAT results — {path.name}\n")
    print(f"- Scenarios: {n} · Pass {passed} · Fail {failed} · Not run {len(not_run)}"
          + (f" · Other {len(odd)}" if odd else ""))
    print(f"- Pass rate (of executed): {round(100 * passed / (passed + failed)) if passed + failed else 0}%")
    testers = sorted({s["tester"] for s in scenarios if s["tester"]})
    dates = sorted({s["date"] for s in scenarios if s["date"]})
    if testers:
        print(f"- Testers: {', '.join(testers)}")
    if dates:
        print(f"- Dates: {dates[0]} … {dates[-1]}" if len(dates) > 1 else f"- Date: {dates[0]}")
    for title, rows in (("Failed", [s for s in scenarios if s["result"] == "Fail"]),
                        ("Not run", not_run), ("Unrecognised result", odd)):
        if rows:
            print(f"\n## {title}\n\n| Scenario | Business flow | Result | Comment | Tester |\n|---|---|---|---|---|")
            for s in rows:
                print(f"| {s['id']} | {s['flow']} | {s['result']} | {s['comment']} | {s['tester']} |")
    if defects:
        print("\n## Defects\n\n| ID | Scenario | Description | Severity | Status |\n|---|---|---|---|---|")
        for d in defects:
            print(f"| {d['id']} | {d['scenario']} | {d['description']} | {d['severity']} | {d['status']} |")
    if a.out_json:
        Path(a.out_json).write_text(json.dumps({"scenarios": scenarios, "defects": defects},
                                               ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nwrote {a.out_json}", file=sys.stderr)


if __name__ == "__main__":
    main()
