# /// script
# requires-python = ">=3.10"
# dependencies = ["python-docx==1.2.0"]
# ///
"""Render a testkit report model (JSON) into a Word document.

    uv run build_docx_report.py model.json out.docx

Model:
{
  "title": "Test report — PROJ-123",
  "subtitle": "Checkout coupon",                      # optional
  "meta": [["Ticket", "PROJ-123"], ["Verdict", "NOT READY"]],   # optional key/value table
  "landscape": false,                                 # optional
  "sections": [
    {"heading": "Summary", "level": 1, "blocks": [
      {"type": "paragraph", "text": "…", "bold": false},
      {"type": "bullets", "items": ["…", "…"]},
      {"type": "numbered", "items": ["…", "…"]},
      {"type": "table", "columns": ["Case", "Status"], "rows": [["TC-S1-001", "PASS"]],
       "widths": [3, 1]},                             # relative widths, optional
      {"type": "image", "path": "qa/runs/…/TC-S2-004-fail.png", "caption": "…", "width_cm": 15},
      {"type": "kv", "rows": [["Severity", "major"], ["Status", "open"]]},
      {"type": "page_break"}
    ]}
  ]
}

Cells whose whole text is a known status or severity (PASS, FAIL, BLOCKED, SKIPPED, APPROVED,
CHANGES_REQUESTED, READY, NOT READY, blocker, critical, major, minor, trivial, open, fixed,
verified, reopened, …) are colour-coded. Paths are resolved relative to the current directory.
"""
import json
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

FONT = "Arial"  # covers Vietnamese diacritics on every OS
GREEN, RED, AMBER, GREY, BLUE = "D9F2E3", "FADBD8", "FDEBD0", "EAECEE", "D6EAF8"
STATUS_FILL = {
    "pass": GREEN, "passed": GREEN, "approved": GREEN, "ready": GREEN, "verified": GREEN,
    "fail": RED, "failed": RED, "not ready": RED, "blocker": RED, "critical": RED, "reopened": RED,
    "changes_requested": AMBER, "blocked": AMBER, "major": AMBER, "open": AMBER,
    "ready with known issues": AMBER,
    "skipped": GREY, "minor": GREY, "trivial": GREY, "wont_fix": GREY, "duplicate": GREY,
    "fixed": BLUE,
}


def shade(cell, fill):
    """Cell background. ShadingType CLEAR, never SOLID (renders black)."""
    tc_pr = cell._tc.get_or_add_tcPr()
    for old in tc_pr.findall(qn("w:shd")):
        tc_pr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def repeat_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    tr_pr.append(el)


def set_cell_text(cell, text, bold=False, size=9):
    cell.text = ""
    lines = str(text if text is not None else "").split("\n")
    p = cell.paragraphs[0]
    for i, line in enumerate(lines):  # never embed \n: one paragraph per line
        if i:
            p = cell.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(line)
        r.bold = bold
        r.font.size = Pt(size)


def style_document(doc):
    st = doc.styles
    normal = st["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.paragraph_format.space_after = Pt(4)
    for name, size, before, after in (("Title", 22, 0, 6), ("Heading 1", 15, 14, 6),
                                      ("Heading 2", 12.5, 10, 4), ("Heading 3", 11, 8, 3)):
        s = st[name]
        s.font.name = FONT
        s.font.size = Pt(size)
        s.font.bold = True
        s.font.color.rgb = RGBColor(0x1F, 0x2D, 0x3D)
        s.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        s.paragraph_format.space_before = Pt(before)
        s.paragraph_format.space_after = Pt(after)
        s.paragraph_format.keep_with_next = True


def add_page_number_footer(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for tag, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if tag:
            fld = OxmlElement("w:fldChar")
            fld.set(qn("w:fldCharType"), tag)
            run._r.append(fld)
        else:
            instr = OxmlElement("w:instrText")
            instr.set(qn("xml:space"), "preserve")
            instr.text = text
            run._r.append(instr)
    run.font.size = Pt(8)


def content_width_cm(section):
    return (section.page_width - section.left_margin - section.right_margin) / 360000


def add_table(doc, columns, rows, widths=None, header=True):
    ncols = len(columns) if columns else max((len(r) for r in rows), default=1)
    table = doc.add_table(rows=0, cols=ncols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    total = content_width_cm(doc.sections[-1])
    rel = widths if widths and len(widths) == ncols else [1] * ncols
    col_cm = [total * w / sum(rel) for w in rel]
    if header and columns:
        hrow = table.add_row()
        repeat_header(hrow)
        for i, c in enumerate(columns):
            set_cell_text(hrow.cells[i], c, bold=True)
            shade(hrow.cells[i], "D5DBE1")
    for r in rows:
        row = table.add_row()
        for i in range(ncols):
            val = r[i] if i < len(r) else ""
            set_cell_text(row.cells[i], val)
            fill = STATUS_FILL.get(str(val).strip().lower())
            if fill:
                shade(row.cells[i], fill)
    for i, w in enumerate(col_cm):  # widths on the column AND every cell, or Word ignores them
        table.columns[i].width = Cm(w)
        for cell in table.columns[i].cells:
            cell.width = Cm(w)
    fix_table_layout(table, total, header=header and bool(columns))
    doc.add_paragraph()


def fix_table_layout(table, total_cm, header=True):
    """Explicit table width, fixed layout and borders, so every viewer renders the same grid."""
    tbl_pr = table._tbl.tblPr
    for tag in ("w:tblW", "w:tblLayout", "w:tblBorders"):
        for old in tbl_pr.findall(qn(tag)):
            tbl_pr.remove(old)
    tbl_w = OxmlElement("w:tblW")
    tbl_w.set(qn("w:w"), str(int(total_cm * 567)))  # 1 cm = 567 dxa
    tbl_w.set(qn("w:type"), "dxa")
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), "4")
        e.set(qn("w:space"), "0")
        e.set(qn("w:color"), "A6ACAF" if header else "D5D8DC")
        borders.append(e)
    # schema order inside tblPr: tblStyle, ..., tblW, jc, ..., tblBorders, ..., tblLayout, ...
    style = tbl_pr.find(qn("w:tblStyle"))
    anchor = style if style is not None else None
    if anchor is not None:
        anchor.addnext(tbl_w)
    else:
        tbl_pr.insert(0, tbl_w)
    jc = tbl_pr.find(qn("w:jc"))
    (jc if jc is not None else tbl_w).addnext(borders)
    borders.addnext(layout)


def add_list(doc, items, numbered):
    style = "List Number" if numbered else "List Bullet"
    for it in items:
        doc.add_paragraph(str(it), style=style)


def add_image(doc, block, base):
    path = (base / block["path"]).resolve() if not Path(block["path"]).is_absolute() else Path(block["path"])
    if not path.exists():
        doc.add_paragraph(f"[missing image: {block['path']}]").runs[0].italic = True
        return
    width = min(float(block.get("width_cm", 15)), content_width_cm(doc.sections[-1]))
    doc.add_picture(str(path), width=Cm(width))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    if block.get("caption"):
        cap = doc.add_paragraph(block["caption"])
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for r in cap.runs:
            r.italic = True
            r.font.size = Pt(9)


def render(model, out, base):
    doc = Document()
    style_document(doc)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)  # A4
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Cm(2))
    sec.top_margin = sec.bottom_margin = Cm(2)
    if model.get("landscape"):
        sec.orientation = WD_ORIENT.LANDSCAPE
        sec.page_width, sec.page_height = sec.page_height, sec.page_width
    add_page_number_footer(sec)

    doc.add_paragraph(model.get("title", "Test report"), style="Title")
    if model.get("subtitle"):
        p = doc.add_paragraph(model["subtitle"])
        p.runs[0].font.size = Pt(12)
    if model.get("meta"):
        add_table(doc, ["", ""], model["meta"], widths=[1, 3], header=False)

    for s in model.get("sections", []):
        if s.get("heading"):
            doc.add_heading(s["heading"], level=max(1, min(int(s.get("level", 1)), 3)))
        for b in s.get("blocks", []):
            t = b.get("type")
            if t == "paragraph":
                p = doc.add_paragraph()
                r = p.add_run(str(b.get("text", "")))
                r.bold = bool(b.get("bold"))
            elif t in ("bullets", "numbered"):
                add_list(doc, b.get("items", []), numbered=(t == "numbered"))
            elif t == "table":
                add_table(doc, b.get("columns", []), b.get("rows", []), b.get("widths"))
            elif t == "kv":
                add_table(doc, ["", ""], b.get("rows", []), widths=[1, 3], header=False)
            elif t == "image":
                add_image(doc, b, base)
            elif t == "page_break":
                doc.add_page_break()
            else:
                raise SystemExit(f"unknown block type: {t!r}")

    # python-docx's default template has <w:zoom> without the schema-required w:percent.
    for zoom in doc.settings.element.findall(qn("w:zoom")):
        if zoom.get(qn("w:percent")) is None:
            zoom.set(qn("w:percent"), "100")

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: uv run build_docx_report.py model.json out.docx")
    model_path, out = Path(sys.argv[1]), Path(sys.argv[2])
    model = json.loads(model_path.read_text(encoding="utf-8"))
    render(model, out, Path.cwd())
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
