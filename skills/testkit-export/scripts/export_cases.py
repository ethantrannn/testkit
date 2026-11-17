# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Read testkit case files (qa/runs/<RUN_ID>/cases/*.md) and write them as JSON, an Excel
workbook model for build_xlsx.py, or a CSV import file for TestRail or Xray. Stdlib only.

    uv run export_cases.py --to json        -o cases.json      qa/runs/PROJ-123/cases/*.md
    uv run export_cases.py --to xlsx-model  -o cases.xlsx.json qa/runs/PROJ-123/cases/*.md
    uv run export_cases.py --to testrail-csv -o PROJ-123-testrail.csv qa/runs/PROJ-123/cases/*.md
    uv run export_cases.py --to xray-csv    -o PROJ-123-xray.csv qa/runs/PROJ-123/cases/*.md

Options:
  --ticket KEY         ticket key for references/links (default: first KEY-123 in "- Ticket:")
  --layout steps|text  TestRail only: one row per step ("Test Case (Steps)", default) or one row
                       per case ("Test Case (Text)")
  --folder PATH        TestRail section root / Xray Test Repo root (default: the ticket key)
  --labels a,b         Xray only: extra labels (default: testkit)
  --bom                start the CSV with a UTF-8 BOM (helps Excel show Vietnamese text)
  --lang vi|en         xlsx-model only: header language (default vi)

Column layouts and import settings: references/import-formats.md.
"""
import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

FIELD_ALIASES = {
    "priority": ["priority", "ưu tiên", "độ ưu tiên"],
    "type": ["type", "loại"],
    "requirement": ["requirement", "requirements", "yêu cầu"],
    "preconditions": ["preconditions", "precondition", "tiền điều kiện", "điều kiện tiên quyết"],
    "test_data": ["test data", "dữ liệu test", "dữ liệu kiểm thử"],
    "steps": ["steps", "các bước", "bước", "bước thực hiện"],
    "expected": ["expected", "expected result", "expected results", "kết quả mong đợi"],
    "depends_on": ["depends on", "phụ thuộc"],
    "reference": ["reference", "tham chiếu"],
}
ALIAS = {a: k for k, v in FIELD_ALIASES.items() for a in v}
LIST_FIELDS = {"steps", "expected"}
CASE_RE = re.compile(r"^###\s+(TC-[A-Za-z0-9]+-\d+)\s*(?:[—–:-]\s*)?(.*)$")
STREAM_RE = re.compile(r"^#\s+([A-Za-z0-9]+)\s*(?:[—–:-]\s*)?(.*)$")
FIELD_RE = re.compile(r"^-\s+([^:]+?)\s*:\s*(.*)$")
ITEM_RE = re.compile(r"^\s+(?:\d+[.)]|[-*])\s+(.*)$")
KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")

TESTRAIL_PRIORITY = {"P0": "Critical", "P1": "High", "P2": "Medium"}
XRAY_PRIORITY = {"P0": "Highest", "P1": "High", "P2": "Medium"}
TESTRAIL_TYPE = {"permission": "Security", "ui": "Usability", "regression": "Regression",
                 "accessibility": "Accessibility"}  # everything else → Functional


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def strip_md(text):
    """Drop inline code backticks; keep the text."""
    return re.sub(r"`([^`]*)`", r"\1", text).strip()


def parse_table(lines):
    rows = []
    for ln in lines:
        if not ln.strip().startswith("|"):
            continue
        cells = [strip_md(c) for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c) and any(cells):
            continue
        rows.append(cells)
    return rows[1:] if rows else []  # drop the header row


def parse_file(path):
    text = Path(path).read_text(encoding="utf-8")
    stream = {"id": Path(path).stem, "title": "", "ticket": "", "file": str(path),
              "traceability": [], "cases": []}
    section, case, field, trace_lines = None, None, None, []
    for raw in text.splitlines():
        line = raw.rstrip()
        m = STREAM_RE.match(line)
        if m and not line.startswith("##"):
            stream["id"], stream["title"] = m.group(1), strip_md(m.group(2))
            continue
        if line.startswith("## "):
            section = line[3:].strip().lower()
            case, field = None, None
            continue
        m = CASE_RE.match(line)
        if m:
            case = {"id": m.group(1), "title": strip_md(m.group(2)), "stream": stream["id"],
                    "priority": "", "type": "", "requirement": "", "preconditions": "",
                    "test_data": "", "steps": [], "expected": [], "depends_on": "",
                    "reference": ""}
            stream["cases"].append(case)
            field = None
            continue
        if case is None:
            if section and section.startswith(("traceability", "truy vết")):
                trace_lines.append(line)
            m = FIELD_RE.match(line)
            if m and m.group(1).strip().lower() == "ticket" and not stream["ticket"]:
                stream["ticket"] = strip_md(m.group(2))
            continue
        m = FIELD_RE.match(line)
        if m:
            key = ALIAS.get(m.group(1).strip().lower())
            field = key
            if key in LIST_FIELDS:
                if m.group(2).strip():
                    case[key].append(strip_md(m.group(2)))
            elif key:
                case[key] = strip_md(m.group(2))
            continue
        m = ITEM_RE.match(line)
        if m and field in LIST_FIELDS:
            case[field].append(strip_md(m.group(1)))
        elif line.strip() and field and field not in LIST_FIELDS and raw.startswith("  "):
            case[field] = (case[field] + " " + strip_md(line)).strip()  # wrapped line
    stream["traceability"] = parse_table(trace_lines)
    return stream


def ticket_key(streams, override):
    if override:
        return override
    for s in streams:
        m = KEY_RE.search(s["ticket"])
        if m:
            return m.group(0)
    return streams[0]["ticket"].split()[0] if streams and streams[0]["ticket"] else "TESTKIT"


def numbered(items):
    return "\n".join(f"{i}. {s}" for i, s in enumerate(items, 1))


def bulleted(items):
    return "\n".join(f"- {s}" for s in items)


def preconditions_text(c):
    parts = [c["preconditions"]]
    if c["test_data"]:
        parts.append(f"Test data: {c['test_data']}")
    if c["depends_on"]:
        parts.append(f"Depends on: {c['depends_on']}")
    return "\n".join(p for p in parts if p)


def safe_path_part(text, sep):
    return re.sub(r"\s+", " ", text.replace(sep, "-")).strip()


def to_xlsx_model(streams, key, lang):
    vi = lang == "vi"
    h = (["ID", "Stream", "Tiêu đề", "Ưu tiên", "Loại", "Yêu cầu", "Tiền điều kiện",
          "Dữ liệu test", "Các bước", "Kết quả mong đợi", "Status", "Ghi chú"] if vi else
         ["ID", "Stream", "Title", "Priority", "Type", "Requirement", "Preconditions",
          "Test data", "Steps", "Expected", "Status", "Notes"])
    widths = [13, 8, 30, 8, 11, 12, 28, 22, 45, 40, 11, 22]
    cols = [{"header": x, "width": w} for x, w in zip(h, widths)]
    cols[3]["choices"], cols[10]["choices"] = "priority", "status"
    rows = [[c["id"], c["stream"], c["title"], c["priority"], c["type"], c["requirement"],
             c["preconditions"], c["test_data"], numbered(c["steps"]), bulleted(c["expected"]),
             "", ""] for s in streams for c in s["cases"]]
    trace = [[s["id"]] + (r + ["", "", ""])[:3] for s in streams for r in s["traceability"]]
    th = (["Stream", "Yêu cầu", "Nguồn", "Test case"] if vi else
          ["Stream", "Requirement", "Source", "Test cases"])
    streams_rows = [[s["id"], s["title"], len(s["cases"])] for s in streams]
    sh = ["Stream", "Tiêu đề" if vi else "Title", "Số case" if vi else "Cases"]
    title = f"{'Test case' if vi else 'Test cases'} — {key}"
    return {"properties": {"title": title},
            "sheets": [
                {"name": "Cases", "title": title, "columns": cols, "rows": rows},
                {"name": "Traceability", "columns": [{"header": th[0], "width": 8},
                                                     {"header": th[1], "width": 45},
                                                     {"header": th[2], "width": 35},
                                                     {"header": th[3], "width": 35}],
                 "rows": trace, "landscape": False},
                {"name": "Streams", "columns": [{"header": sh[0], "width": 8},
                                                {"header": sh[1], "width": 50},
                                                {"header": sh[2], "width": 10, "align": "center"}],
                 "rows": streams_rows, "landscape": False}]}


def to_testrail(streams, key, layout, folder):
    root = safe_path_part(folder or key, ">")
    head = ["Section Hierarchy", "Title", "Test ID", "Type", "Priority", "References",
            "Requirement", "Preconditions"]
    head += ["Steps (Step)", "Steps (Expected Result)"] if layout == "steps" else \
        ["Steps", "Expected Result"]
    rows = [head]
    for s in streams:
        name = (s["id"] + " — " + s["title"]).strip(" —")
        section = root + " > " + safe_path_part(name, ">")
        for c in s["cases"]:
            base = [section, c["title"] or c["id"], c["id"],
                    TESTRAIL_TYPE.get(c["type"].lower(), "Functional"),
                    TESTRAIL_PRIORITY.get(c["priority"].upper(), "Medium"), key,
                    c["requirement"], preconditions_text(c)]
            expected = bulleted(c["expected"])
            if layout == "text":
                rows.append(base + [numbered(c["steps"]), expected])
                continue
            steps = c["steps"] or [""]
            for i, step in enumerate(steps):
                first, last = i == 0, i == len(steps) - 1
                rows.append((base if first else [""] * len(base)) + [step, expected if last else ""])
    return rows


def to_xray(streams, key, folder, labels):
    root = safe_path_part(folder or key, "/")
    head = ["Issue Id", "Issue key", "Test type", "Test Summary", "Test Priority", "Labels",
            "Description", "Action", "Data", "Result", "Test Repo", "Tests"]
    rows, n = [head], 0
    for s in streams:
        repo = root + "/" + safe_path_part((s["id"] + " " + s["title"]).strip(), "/")
        for c in s["cases"]:
            n += 1
            summary = f"{c['id']} {c['title']}".strip()
            desc = "\n".join(x for x in [c["preconditions"],
                                         f"Depends on: {c['depends_on']}" if c["depends_on"] else "",
                                         f"Requirement: {c['requirement']}" if c["requirement"] else "",
                                         f"testkit case: {c['id']} ({s['file']})"] if x)
            lab = ";".join([*labels, c["id"], f"{key}-{s['id']}"])
            steps = c["steps"] or [c["title"]]
            for i, step in enumerate(steps):
                first, last = i == 0, i == len(steps) - 1
                data = c["test_data"] if first else ""
                result = bulleted(c["expected"]) if last else ""
                if first:
                    rows.append([n, "", "Manual", summary,
                                 XRAY_PRIORITY.get(c["priority"].upper(), "Medium"), lab, desc,
                                 step, data, result, repo, key])
                else:
                    rows.append([n, "", "Manual", "", "", "", "", step, data, result, "", ""])
    return rows


def write_csv(rows, out, delimiter, bom):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    data = buf.getvalue()
    for line_no, r in enumerate(rows, 1):
        for v in r:
            if isinstance(v, str) and v[:1] in ("=", "+", "@") and len(v) > 1:
                print(f"warning: row {line_no} cell starts with {v[0]!r}; spreadsheet apps may "
                      "read it as a formula", file=sys.stderr)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(("﻿" if bom else "") + data, encoding="utf-8", newline="")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("files", nargs="+", help="cases/*.md files of one run")
    ap.add_argument("--to", required=True, choices=["json", "xlsx-model", "testrail-csv", "xray-csv"])
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--ticket")
    ap.add_argument("--layout", choices=["steps", "text"], default="steps")
    ap.add_argument("--folder")
    ap.add_argument("--labels", default="testkit")
    ap.add_argument("--bom", action="store_true")
    ap.add_argument("--lang", choices=["vi", "en"], default="vi")
    a = ap.parse_args()

    for f in a.files:
        if not Path(f).is_file():
            fail(f"not a file: {f}")
    streams = [parse_file(f) for f in sorted(a.files)]
    total = sum(len(s["cases"]) for s in streams)
    if total == 0:
        fail("no test cases found (expected '### TC-<STREAM>-<NNN> — <title>' headings)")
    for s in streams:
        for c in s["cases"]:
            if not c["steps"]:
                print(f"warning: {c['id']} has no steps", file=sys.stderr)
            if not c["expected"]:
                print(f"warning: {c['id']} has no expected results", file=sys.stderr)
    key = ticket_key(streams, a.ticket)
    out = Path(a.out)
    if a.to == "json":
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"ticket": key, "streams": streams}, ensure_ascii=False,
                                  indent=1), encoding="utf-8")
    elif a.to == "xlsx-model":
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(to_xlsx_model(streams, key, a.lang), ensure_ascii=False,
                                  indent=1), encoding="utf-8")
    elif a.to == "testrail-csv":
        write_csv(to_testrail(streams, key, a.layout, a.folder), out, ",", a.bom)
    else:
        labels = [x.strip() for x in a.labels.split(",") if x.strip()]
        write_csv(to_xray(streams, key, a.folder, labels), out, ";", a.bom)
    print(f"wrote {out}: {len(streams)} stream(s), {total} case(s), ticket {key}")


if __name__ == "__main__":
    main()
