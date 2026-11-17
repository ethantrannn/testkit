# /// script
# requires-python = ">=3.10"
# dependencies = ["openpyxl==3.1.5"]
# ///
"""Render a testkit workbook model (JSON) into an Excel file, then re-open it and check it.

    uv run build_xlsx.py model.json out.xlsx
    uv run build_xlsx.py --check out.xlsx          # only re-open and check an existing file

Model:
{
  "properties": {"title": "Test cases — PROJ-123", "creator": "testkit"},   # optional
  "sheets": [
    {
      "name": "Cases",                      # ≤31 chars, no []:*?/\\ (cleaned automatically)
      "title": "Test cases — PROJ-123",     # optional bold line above everything
      "meta": [["Ticket", "PROJ-123"], ["Ngày", "2026-11-17"]],   # optional key/value lines
      "columns": [
        {"header": "ID", "width": 14},
        {"header": "Steps", "width": 50},                          # text wraps by default
        {"header": "Status", "width": 12, "choices": "status"},    # dropdown + colour
        {"header": "Cases", "width": 8, "align": "center"}
      ],
      "rows": [["TC-S1-001", "1. Mở /login\\n2. …", "PASS", 3]],
      "blank_rows": 0,          # extra empty rows that keep borders + dropdowns (fill-in sheets)
      "freeze_header": true,    # default true
      "autofilter": true,       # default true
      "landscape": true         # print setup, default true
    }
  ]
}

"choices" is a list of values or a preset name: status (PASS FAIL BLOCKED SKIPPED),
uat (Pass Fail), severity (blocker … trivial), bug_status (open fixed verified reopened
wont_fix duplicate), priority (P0 P1 P2), verdict (READY, READY WITH KNOWN ISSUES, NOT READY),
review (APPROVED CHANGES_REQUESTED), risk (high medium low).

Any cell in the table whose whole text is a known status or severity gets the same fill as in
build_docx_report.py: a static fill for the value written now, plus conditional formatting, so the
colour follows when someone picks another value in the dropdown. Text that starts with "=" is stored as text, never as a
formula: the workbooks hold values only.
"""
import json
import math
import re
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

FONT = "Arial"  # covers Vietnamese diacritics on every OS
# Keep in sync with STATUS_FILL in build_docx_report.py.
GREEN, RED, AMBER, GREY, BLUE = "D9F2E3", "FADBD8", "FDEBD0", "EAECEE", "D6EAF8"
STATUS_FILL = {
    "pass": GREEN, "passed": GREEN, "approved": GREEN, "ready": GREEN, "verified": GREEN,
    "fail": RED, "failed": RED, "not ready": RED, "blocker": RED, "critical": RED, "reopened": RED,
    "changes_requested": AMBER, "blocked": AMBER, "major": AMBER, "open": AMBER,
    "ready with known issues": AMBER,
    "skipped": GREY, "minor": GREY, "trivial": GREY, "wont_fix": GREY, "duplicate": GREY,
    "fixed": BLUE,
}
HEADER_FILL = "D5DBE1"
PRESETS = {
    "status": ["PASS", "FAIL", "BLOCKED", "SKIPPED"],
    "uat": ["Pass", "Fail"],
    "severity": ["blocker", "critical", "major", "minor", "trivial"],
    "bug_status": ["open", "fixed", "verified", "reopened", "wont_fix", "duplicate"],
    "priority": ["P0", "P1", "P2"],
    "verdict": ["READY", "READY WITH KNOWN ISSUES", "NOT READY"],
    "review": ["APPROVED", "CHANGES_REQUESTED"],
    "risk": ["high", "medium", "low"],
}
THIN = Side(style="thin", color="A6ACAF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
LINE_PT = 13  # row height per text line at 10 pt


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def sheet_name(name, used):
    clean = re.sub(r"[\[\]:*?/\\]", "-", str(name or "Sheet")).strip("'") or "Sheet"
    clean = clean[:31].strip() or "Sheet"
    base, n = clean, 2
    while clean.lower() in used:
        suffix = f" ({n})"
        clean = base[: 31 - len(suffix)].strip() + suffix
        n += 1
    used.add(clean.lower())
    return clean


def norm_column(c):
    if isinstance(c, str):
        return {"header": c}
    if not isinstance(c, dict) or "header" not in c:
        fail(f"column must be a string or an object with 'header': {c!r}")
    return c


def choices_of(col):
    ch = col.get("choices")
    if ch is None:
        return None
    if isinstance(ch, str):
        if ch not in PRESETS:
            fail(f"unknown choices preset {ch!r}; use a list or one of {sorted(PRESETS)}")
        return PRESETS[ch]
    return [str(x) for x in ch]


def set_value(cell, value):
    if isinstance(value, bool):
        value = "TRUE" if value else "FALSE"
    if value is None:
        cell.value = None
    elif isinstance(value, (int, float)):
        cell.value = value
    else:
        text = str(value).replace("\r\n", "\n")
        cell.value = text
        if text.startswith("="):  # never a formula: keep it as literal text
            cell.data_type = "s"
            cell.quotePrefix = True


def line_count(value, width):
    if value is None:
        return 1
    per_line = max(1, int(width * 1.15))
    return sum(max(1, math.ceil(len(line) / per_line)) for line in str(value).split("\n"))


def build_sheet(ws, spec):
    columns = [norm_column(c) for c in spec.get("columns", [])]
    rows = spec.get("rows", [])
    if not columns:
        fail(f"sheet {ws.title!r} has no columns")
    ncols = len(columns)
    for i, r in enumerate(rows):
        if not isinstance(r, list):
            fail(f"sheet {ws.title!r} row {i + 1} is not a list")
        if len(r) > ncols:
            fail(f"sheet {ws.title!r} row {i + 1} has {len(r)} cells but {ncols} columns")
    widths = [float(c.get("width", 15)) for c in columns]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    base_font = Font(name=FONT, size=10)
    r = 1
    if spec.get("title"):
        cell = ws.cell(row=r, column=1)
        set_value(cell, spec["title"])
        cell.font = Font(name=FONT, size=14, bold=True)
        ws.row_dimensions[r].height = 22
        r += 2
    for key, val in spec.get("meta", []) or []:
        k = ws.cell(row=r, column=1)
        set_value(k, key)
        k.font = Font(name=FONT, size=10, bold=True)
        v = ws.cell(row=r, column=2)
        set_value(v, val)
        v.font = base_font
        v.alignment = Alignment(vertical="top")
        fill = STATUS_FILL.get(str(val).strip().lower())
        if fill:
            v.fill = PatternFill("solid", fgColor=fill)
        r += 1
    if spec.get("meta"):
        r += 1

    header_row = r
    for i, col in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=i)
        set_value(cell, col["header"])
        cell.font = Font(name=FONT, size=10, bold=True)
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(wrap_text=True, vertical="center",
                                   horizontal=col.get("align", "left"))
        cell.border = BORDER
    ws.row_dimensions[header_row].height = LINE_PT * max(
        line_count(c["header"], w) for c, w in zip(columns, widths)) + 6

    blank = int(spec.get("blank_rows", 0))
    last_row = header_row + len(rows) + blank
    for ri in range(len(rows) + blank):
        row_vals = rows[ri] if ri < len(rows) else []
        excel_row = header_row + 1 + ri
        lines = 1
        for ci, col in enumerate(columns, start=1):
            val = row_vals[ci - 1] if ci - 1 < len(row_vals) else None
            cell = ws.cell(row=excel_row, column=ci)
            set_value(cell, val)
            cell.font = base_font
            cell.border = BORDER
            cell.alignment = Alignment(wrap_text=col.get("wrap", True), vertical="top",
                                       horizontal=col.get("align", "left"))
            fill = STATUS_FILL.get(str(val).strip().lower()) if val is not None else None
            if fill:  # static fill for viewers without conditional formatting (Quick Look, importers)
                cell.fill = PatternFill("solid", fgColor=fill)
            if col.get("wrap", True):
                lines = max(lines, line_count(val, widths[ci - 1]))
        ws.row_dimensions[excel_row].height = min(409, LINE_PT * lines + 4)

    first_col, last_col = "A", get_column_letter(ncols)
    data_ref = f"{first_col}{header_row + 1}:{last_col}{max(last_row, header_row + 1)}"
    if last_row > header_row:
        # Status colours: one rule per fill colour, exact (case-insensitive) whole-cell match.
        by_fill = {}
        for word, fill in STATUS_FILL.items():
            by_fill.setdefault(fill, []).append(word)
        tl = f"{first_col}{header_row + 1}"
        for fill, words in by_fill.items():
            cond = ",".join(f'TRIM({tl})="{w}"' for w in words)
            ws.conditional_formatting.add(
                data_ref, FormulaRule(formula=[f"OR({cond})"],
                                      fill=PatternFill("solid", fgColor=fill, bgColor=fill)))
        for ci, col in enumerate(columns, start=1):
            ch = choices_of(col)
            if not ch:
                continue
            listing = ",".join(ch)
            if len(listing) > 255 or any("," in x or '"' in x for x in ch):
                fail(f"choices of column {col['header']!r}: no commas or quotes, ≤255 chars total")
            dv = DataValidation(type="list", formula1=f'"{listing}"', allow_blank=True,
                                showDropDown=False)  # False = show the in-cell arrow
            dv.error, dv.errorTitle = f"Choose one of: {', '.join(ch)}", col["header"]
            dv.showErrorMessage = True
            letter = get_column_letter(ci)
            dv.add(f"{letter}{header_row + 1}:{letter}{last_row}")
            ws.add_data_validation(dv)

    if spec.get("freeze_header", True):
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    if spec.get("autofilter", True):
        ws.auto_filter.ref = f"{first_col}{header_row}:{last_col}{max(last_row, header_row)}"
    ws.print_title_rows = f"{header_row}:{header_row}"
    ws.page_setup.orientation = "landscape" if spec.get("landscape", True) else "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    return header_row, len(rows)


def render(model, out):
    sheets = model.get("sheets")
    if not sheets:
        fail("model has no sheets")
    wb = Workbook()
    wb.remove(wb.active)
    used, expected = set(), []
    for spec in sheets:
        ws = wb.create_sheet(sheet_name(spec.get("name"), used))
        header_row, nrows = build_sheet(ws, spec)
        expected.append((ws.title, header_row, nrows, len(spec["columns"])))
    props = model.get("properties", {})
    wb.properties.title = props.get("title")
    wb.properties.creator = props.get("creator", "testkit")
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out))
    return expected


def check(path, expected=None):
    """Re-open the file, count formulas and compare the shape with the model."""
    try:
        wb = load_workbook(str(path))
    except Exception as e:  # noqa: BLE001
        fail(f"cannot re-open {path}: {e}")
    problems, formulas = [], []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.data_type == "f":
                    formulas.append(f"{ws.title}!{c.coordinate}")
                elif isinstance(c.value, str) and re.match(r"^#(REF!|VALUE!|NAME\?|DIV/0!|N/A)", c.value):
                    problems.append(f"{ws.title}!{c.coordinate}: error value {c.value}")
    for title, header_row, nrows, ncols in expected or []:
        ws = wb[title]
        if ws.max_column < ncols:
            problems.append(f"{title}: {ws.max_column} columns, expected {ncols}")
        if ws.max_row < header_row + nrows:
            problems.append(f"{title}: {ws.max_row} rows, expected ≥{header_row + nrows}")
    summary = ", ".join(f"{ws.title} ({ws.max_row}×{ws.max_column})" for ws in wb.worksheets)
    print(f"check: re-opened {path}: {summary}")
    if formulas:
        print(f"check: {len(formulas)} formula cell(s), e.g. {formulas[:5]} — recalculate and "
              "check them with the xlsx skill's recalc.py (needs LibreOffice)")
    else:
        print("check: no formulas")
    if problems:
        for p in problems:
            print(f"check: PROBLEM {p}", file=sys.stderr)
        sys.exit(2)
    print("check: OK")


def main():
    args = sys.argv[1:]
    if args[:1] in (["-h"], ["--help"]) or not args:
        print(__doc__)
        sys.exit(0 if args else 1)
    if args[0] == "--check":
        if len(args) != 2:
            fail("usage: uv run build_xlsx.py --check file.xlsx")
        check(Path(args[1]))
        return
    if len(args) != 2:
        fail("usage: uv run build_xlsx.py model.json out.xlsx")
    model_path, out = Path(args[0]), Path(args[1])
    if out.suffix.lower() != ".xlsx":
        fail("output file must end in .xlsx")
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"model not found: {model_path}")
    except json.JSONDecodeError as e:
        fail(f"invalid JSON in {model_path}: {e}")
    expected = render(model, out)
    print(f"wrote {out}")
    check(out, expected)


if __name__ == "__main__":
    main()
