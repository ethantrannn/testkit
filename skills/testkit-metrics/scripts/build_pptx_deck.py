# /// script
# requires-python = ">=3.10"
# dependencies = ["python-pptx==1.0.2"]
# ///
"""Render a testkit deck model (JSON) into a 16:9 PowerPoint deck with native charts.

    uv run build_pptx_deck.py deck.json out.pptx [--split DIR]

--split DIR also writes DIR/slide-NN.pptx, one single-slide deck per slide, so a viewer that only
renders the first slide (macOS Quick Look: qlmanage -t) can preview every slide.

Model:
{
  "title": "Quality report — Sprint 46",
  "theme": {"primary": "0B3C49", "font": "Arial"},             # optional overrides
  "slides": [
    {"type": "title",   "title": "…", "subtitle": "…"},
    {"type": "kpis",    "title": "Key figures", "text": "one-paragraph summary (optional)",
                        "tiles": [{"label": "Pass rate", "value": "92%", "note": "31 of 38", "tone": "good|warn|bad|neutral"}]},
    {"type": "chart",   "title": "…", "chart": "column|stacked_column|bar|stacked_bar|line|pie|doughnut",
                        "categories": ["A", "B"], "series": [{"name": "PASS", "values": [3, 4]}],
                        "bullets": ["optional commentary, shown right of the chart"]},
    {"type": "table",   "title": "…", "columns": ["ID", "Status"], "rows": [["BUG-1", "open"]],
                        "widths": [3, 1], "max_rows": 9},            # long tables continue on extra slides
    {"type": "bullets", "title": "…", "items": ["…"]},
    {"type": "bullets", "title": "…", "groups": [{"title": "Findings", "items": ["…"]}, {"title": "Next steps", "items": ["…"]}]}
  ]
}
Every slide also takes "notes" (speaker notes). Series/categories named PASS, FAIL, BLOCKED, SKIPPED or a
severity (blocker … trivial) get fixed status colours; table cells whose whole text is a status or severity
are colour-coded like the Word export. Up to 6 KPI tiles, up to ~8 bullets per slide.
"""
import argparse
import copy
import json
import sys
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn
from pptx.util import Emu, Inches, Pt

W, H, M = 13.333, 7.5, 0.6  # slide size and side margin, inches
THEME = {"primary": "0B3C49", "text": "1F2A33", "muted": "5B6B77", "tile": "EEF3F5", "line": "D5DDE2",
         "white": "FFFFFF", "font": "Arial"}  # Arial: same metrics everywhere, matches the Word export
TONE = {"good": "1E8C5A", "warn": "B7791F", "bad": "C0392B", "neutral": "0B3C49"}
STATUS = {"pass": "2E9E6B", "fail": "C8414B", "blocked": "E3A33B", "skipped": "9AA5B1",
          "blocker": "8E1B2C", "critical": "C8414B", "major": "E3A33B", "minor": "7FA7C9", "trivial": "B8C2CC"}
CELL_FILL = {"pass": "D9F2E3", "passed": "D9F2E3", "verified": "D9F2E3", "ready": "D9F2E3",
             "fail": "FADBD8", "not ready": "FADBD8", "blocker": "FADBD8", "critical": "FADBD8", "reopened": "FADBD8",
             "blocked": "FDEBD0", "major": "FDEBD0", "open": "FDEBD0", "ready with known issues": "FDEBD0",
             "skipped": "EAECEE", "minor": "EAECEE", "trivial": "EAECEE", "wont_fix": "EAECEE", "duplicate": "EAECEE",
             "fixed": "D6EAF8"}
CHARTS = {"column": XL_CHART_TYPE.COLUMN_CLUSTERED, "stacked_column": XL_CHART_TYPE.COLUMN_STACKED,
          "bar": XL_CHART_TYPE.BAR_CLUSTERED, "stacked_bar": XL_CHART_TYPE.BAR_STACKED,
          "line": XL_CHART_TYPE.LINE_MARKERS, "pie": XL_CHART_TYPE.PIE, "doughnut": XL_CHART_TYPE.DOUGHNUT}
PALETTE = ["0B3C49", "3A8DA8", "E07A5F", "81B29A", "F2CC8F", "6D597A"]


def rgb(h):
    return RGBColor.from_string(h)


def text_box(slide, x, y, w, h, text, size=14, bold=False, color=None, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, name=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    lines = text if isinstance(text, list) else [text]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = str(line)
        f = r.font
        f.size, f.bold, f.name = Pt(size), bold, THEME["font"]
        f.color.rgb = rgb(color or THEME["text"])
    return tb


def bullets(slide, x, y, w, h, items, size=16):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tb.name = "Bullets"
    tf = tb.text_frame
    tf.word_wrap = True
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(8)
        pPr = p._p.get_or_add_pPr()  # real bullet (no literal "•"), hanging indent
        pPr.set("marL", str(Inches(0.25)))
        pPr.set("indent", str(-Inches(0.25)))
        bu = pPr.makeelement("{http://schemas.openxmlformats.org/drawingml/2006/main}buChar", {"char": "•"})
        pPr.append(bu)
        r = p.add_run()
        r.text = str(it)
        r.font.size, r.font.name = Pt(size), THEME["font"]
        r.font.color.rgb = rgb(THEME["text"])
    return tb


def slide_title(slide, title):
    text_box(slide, M, 0.45, W - 2 * M, 0.85, title, size=32, bold=True, color=THEME["primary"],
             anchor=MSO_ANCHOR.MIDDLE, name="Title")


def notes(slide, s):
    if s.get("notes"):
        slide.notes_slide.notes_text_frame.text = s["notes"]


def add_title_slide(prs, s):
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    bg = sl.background.fill
    bg.solid()
    bg.fore_color.rgb = rgb(THEME["primary"])
    text_box(sl, M + 0.2, 2.3, W - 2 * M - 0.4, 1.6, s.get("title", ""), size=44, bold=True, color=THEME["white"],
             anchor=MSO_ANCHOR.BOTTOM, name="Title")
    if s.get("subtitle"):
        text_box(sl, M + 0.2, 4.1, W - 2 * M - 0.4, 0.8, s["subtitle"], size=20, color="CFE3EA", name="Subtitle")
    notes(sl, s)


def add_kpis(prs, s):
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    slide_title(sl, s.get("title", ""))
    tiles = s.get("tiles", [])[:6]
    cols = 3 if len(tiles) > 4 else max(1, len(tiles))
    gap, top = 0.3, 1.6
    tw = (W - 2 * M - gap * (cols - 1)) / cols
    th = 1.95
    for i, t in enumerate(tiles):
        x, y = M + (i % cols) * (tw + gap), top + (i // cols) * (th + gap)
        box = sl.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(tw), Inches(th))
        box.name = f"KPI {i + 1}"
        box.adjustments[0] = 0.08
        box.fill.solid()
        box.fill.fore_color.rgb = rgb(THEME["tile"])
        box.line.fill.background()
        box.shadow.inherit = False
        text_box(sl, x + 0.25, y + 0.15, tw - 0.5, 0.45, t.get("label", ""), size=14, bold=True, color=THEME["muted"])
        text_box(sl, x + 0.25, y + 0.55, tw - 0.5, 0.9, t.get("value", ""), size=40, bold=True,
                 color=TONE.get(t.get("tone"), TONE["neutral"]))
        if t.get("note"):
            text_box(sl, x + 0.25, y + 1.42, tw - 0.5, 0.45, t["note"], size=12, color=THEME["muted"])
    rows = (len(tiles) + cols - 1) // cols
    if s.get("text"):
        y = top + rows * (th + gap) + 0.05
        text_box(sl, M, y, W - 2 * M, H - y - 0.35, s["text"], size=15, color=THEME["text"], name="Summary")
    notes(sl, s)


def style_chart(chart, kind, series_names, categories):
    # no frame around the chart area
    chart._chartSpace.find(qn("c:chart")).addnext(
        parse_xml(f'<c:spPr {nsdecls("c", "a")}><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>'))
    chart.font.size = Pt(12)
    chart.font.name = THEME["font"]
    chart.font.color.rgb = rgb(THEME["muted"])
    multi = len(series_names) > 1
    chart.has_legend = multi or kind in ("pie", "doughnut")
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(12)
    plot = chart.plots[0]
    if kind not in ("pie", "doughnut", "line"):
        plot.gap_width = 70
        if kind.startswith("stacked"):
            plot.overlap = 100
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.font.size = Pt(12)
    dl.number_format, dl.number_format_is_linked = "0;;;", False  # hide zero labels
    if kind.startswith("stacked") or kind in ("pie", "doughnut"):
        dl.position = XL_LABEL_POSITION.CENTER
        dl.font.color.rgb = rgb(THEME["white"])
        dl.font.bold = True
    elif kind == "line":
        dl.position = XL_LABEL_POSITION.ABOVE
    else:
        dl.position = XL_LABEL_POSITION.OUTSIDE_END
        dl.font.color.rgb = rgb(THEME["text"])
    by_point = kind in ("pie", "doughnut") or (not multi and any(str(c).lower() in STATUS for c in categories))
    for i, ser in enumerate(plot.series):
        color = STATUS.get(str(series_names[i]).lower(), PALETTE[i % len(PALETTE)])
        if kind == "line":
            ser.format.line.color.rgb = rgb(color)
            ser.format.line.width = Pt(2.5)
            ser.smooth = False
            continue
        ser.format.fill.solid()
        ser.format.fill.fore_color.rgb = rgb(color)
        if by_point:
            for j, c in enumerate(categories):
                pt = ser.points[j]
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = rgb(STATUS.get(str(c).lower(), PALETTE[j % len(PALETTE)]))
    if kind not in ("pie", "doughnut"):
        va, ca = chart.value_axis, chart.category_axis
        va.has_major_gridlines = True
        va.major_gridlines.format.line.color.rgb = rgb(THEME["line"])
        va.major_gridlines.format.line.width = Pt(0.75)
        va.format.line.fill.background()
        va.tick_labels.font.size = Pt(12)
        va.tick_labels.font.color.rgb = rgb(THEME["muted"])
        ca.tick_labels.font.size = Pt(12)
        ca.tick_labels.font.color.rgb = rgb(THEME["muted"])
        ca.format.line.color.rgb = rgb(THEME["line"])
        ca.has_major_gridlines = False
        if kind.endswith("bar"):
            ca.reverse_order = True  # first category on top


def add_chart(prs, s):
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    slide_title(sl, s.get("title", ""))
    kind = s.get("chart", "column")
    if kind not in CHARTS:
        raise SystemExit(f"unknown chart type {kind!r} (use: {', '.join(CHARTS)})")
    cd = CategoryChartData()
    cd.categories = [str(c) for c in s["categories"]]
    names = []
    for ser in s["series"]:
        if len(ser["values"]) != len(s["categories"]):
            raise SystemExit(f"slide {s.get('title')!r}: series {ser['name']!r} has {len(ser['values'])} values "
                             f"for {len(s['categories'])} categories")
        cd.add_series(str(ser["name"]), [float(v) if v is not None else None for v in ser["values"]])
        names.append(ser["name"])
    has_side = bool(s.get("bullets"))
    cw = 8.1 if has_side else W - 2 * M
    gf = sl.shapes.add_chart(CHARTS[kind], Inches(M), Inches(1.55), Inches(cw), Inches(5.4), cd)
    gf.name = "Chart"
    style_chart(gf.chart, kind, names, s["categories"])
    if has_side:
        x = M + cw + 0.4
        panel = sl.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(1.7), Inches(W - M - x), Inches(5.1))
        panel.name = "Commentary panel"
        panel.adjustments[0] = 0.05
        panel.fill.solid()
        panel.fill.fore_color.rgb = rgb(THEME["tile"])
        panel.line.fill.background()
        panel.shadow.inherit = False
        bullets(sl, x + 0.2, 1.9, W - M - x - 0.4, 4.7, s["bullets"][:8], size=14)
    notes(sl, s)


def fill_cell(cell, text, size, bold=False, color=None, fill=None):
    cell.text = ""
    tf = cell.text_frame
    tf.word_wrap = True
    lines = str(text).split("\n")
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = line
        r.font.size, r.font.bold, r.font.name = Pt(size), bold, THEME["font"]
        r.font.color.rgb = rgb(color or THEME["text"])
    cell.margin_left = cell.margin_right = Inches(0.08)
    cell.margin_top = cell.margin_bottom = Inches(0.04)
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    cell.fill.solid()
    cell.fill.fore_color.rgb = rgb(fill or THEME["white"])


def add_table(prs, s):
    cols, rows = s["columns"], s.get("rows", [])
    per = int(s.get("max_rows", 9))
    chunks = [rows[i:i + per] for i in range(0, len(rows), per)] or [[]]
    for k, chunk in enumerate(chunks):
        sl = prs.slides.add_slide(prs.slide_layouts[6])
        slide_title(sl, s.get("title", "") + (f" ({k + 1}/{len(chunks)})" if len(chunks) > 1 else ""))
        size = 14 if len(chunk) <= 6 else 12
        rh = 0.5 if size == 14 else 0.44
        tw = W - 2 * M
        gf = sl.shapes.add_table(len(chunk) + 1, len(cols), Inches(M), Inches(1.6), Inches(tw), Inches(rh * (len(chunk) + 1)))
        gf.name = "Table"
        tbl = gf.table
        tbl.first_row, tbl.horz_banding = True, False
        rel = s.get("widths") if s.get("widths") and len(s["widths"]) == len(cols) else [1] * len(cols)
        for i, wv in enumerate(rel):
            tbl.columns[i].width = Emu(int(Inches(tw) * wv / sum(rel)))
        for i, c in enumerate(cols):
            fill_cell(tbl.cell(0, i), c, size, bold=True, color=THEME["white"], fill=THEME["primary"])
        for r_i, row in enumerate(chunk, start=1):
            tbl.rows[r_i].height = Inches(rh)
            for c_i in range(len(cols)):
                v = row[c_i] if c_i < len(row) else ""
                fill_cell(tbl.cell(r_i, c_i), v, size, fill=CELL_FILL.get(str(v).strip().lower()))
        notes(sl, s)


def add_bullets(prs, s):
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    slide_title(sl, s.get("title", ""))
    groups = s.get("groups") or [{"title": None, "items": s.get("items", [])}]
    gap = 0.3
    pw = (W - 2 * M - gap * (len(groups) - 1)) / len(groups)
    for i, g in enumerate(groups):
        x = M + i * (pw + gap)
        panel = sl.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(1.6), Inches(pw), Inches(5.3))
        panel.name = f"Panel {i + 1}"
        panel.adjustments[0] = 0.03
        panel.fill.solid()
        panel.fill.fore_color.rgb = rgb(THEME["tile"])
        panel.line.fill.background()
        panel.shadow.inherit = False
        y = 1.85
        if g.get("title"):
            text_box(sl, x + 0.3, y, pw - 0.6, 0.5, g["title"], size=20, bold=True, color=THEME["primary"])
            y += 0.65
        bullets(sl, x + 0.3, y, pw - 0.6, 6.7 - y, (g.get("items") or [])[:8], size=18 if len(groups) == 1 else 16)
    notes(sl, s)


BUILDERS = {"title": add_title_slide, "kpis": add_kpis, "chart": add_chart, "table": add_table, "bullets": add_bullets}


def render(model, slides, out):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    prs.core_properties.title = model.get("title", "")
    prs.core_properties.author = "testkit"
    for s in slides:
        t = s.get("type")
        if t not in BUILDERS:
            raise SystemExit(f"unknown slide type {t!r} (use: {', '.join(BUILDERS)})")
        BUILDERS[t](prs, s)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    return len(prs.slides)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("model")
    ap.add_argument("out")
    ap.add_argument("--split", help="also write one single-slide deck per slide into this folder (for previews)")
    a = ap.parse_args()
    mp = Path(a.model)
    if not mp.exists():
        sys.exit(f"build_pptx_deck: {mp} not found")
    model = json.loads(mp.read_text(encoding="utf-8"))
    THEME.update({k: v.lstrip("#") for k, v in (model.get("theme") or {}).items() if k != "font"})
    if (model.get("theme") or {}).get("font"):
        THEME["font"] = model["theme"]["font"]
    slides = model.get("slides") or []
    if not slides:
        sys.exit("build_pptx_deck: model has no slides")
    n = render(model, slides, Path(a.out))
    print(f"wrote {a.out} ({n} slides)")
    if a.split:
        d = Path(a.split)
        k = 0
        for s in slides:
            if s.get("type") == "table" and len(s.get("rows", [])) > int(s.get("max_rows", 9)):
                per = int(s.get("max_rows", 9))
                parts = [dict(copy.deepcopy(s), rows=s["rows"][i:i + per]) for i in range(0, len(s["rows"]), per)]
            else:
                parts = [s]
            for part in parts:
                k += 1
                render(model, [part], d / f"slide-{k:02d}.pptx")
        print(f"wrote {k} single-slide decks to {d}")


if __name__ == "__main__":
    main()
