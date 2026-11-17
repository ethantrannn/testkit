#!/usr/bin/env python3
"""Convert a guide / release notes / FAQ markdown file into the JSON model of
testkit-export/scripts/build_docx_report.py.

    python3 md_to_docx_model.py qa/guides/<NAME>/guide.md qa/guides/<NAME>/guide-docx.json [--subtitle "…"] [--meta "Version=2.3" ...]

Supported markdown (keep guides to this subset):
  # Title                     document title (first one only)
  ## Heading / ### Heading     section headings (level 1 / 2); #### -> level 3
  paragraphs                  consecutive lines are joined; **bold** markers are removed, a line that is
                              entirely **bold** becomes a bold paragraph
  - item / * item             bullets;  1. item  numbered step (kept as typed, so steps split by images
                              and sections number correctly)
  ![caption](path/to/img.png) image (path relative to the markdown file or the project root), caption below
  | a | b | tables            first row = header
  ---                         page break
Images are written relative to the current directory (run from the project root). Stdlib only.
"""
import argparse
import json
import re
import sys
from pathlib import Path


def clean(s):
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("markdown")
    ap.add_argument("out")
    ap.add_argument("--subtitle")
    ap.add_argument("--meta", action="append", default=[], help="Key=Value row under the title (repeatable)")
    ap.add_argument("--image-width", type=float, default=15, help="image width in cm (default 15)")
    a = ap.parse_args()
    src = Path(a.markdown)
    if not src.exists():
        sys.exit(f"md_to_docx_model: {src} not found")
    lines = src.read_text(encoding="utf-8").splitlines()

    model = {"title": "", "sections": []}
    if a.subtitle:
        model["subtitle"] = a.subtitle
    if a.meta:
        model["meta"] = [m.split("=", 1) if "=" in m else [m, ""] for m in a.meta]
    sec = {"heading": None, "level": 1, "blocks": []}
    model["sections"].append(sec)
    para, i = [], 0
    missing = []

    def flush():
        if para:
            text = " ".join(para)
            bold = bool(re.fullmatch(r"\*\*.+\*\*", text))
            sec["blocks"].append({"type": "paragraph", "text": clean(text), **({"bold": True} if bold else {})})
            para.clear()

    while i < len(lines):
        line = lines[i].rstrip()
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        img = re.match(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$", line.strip())
        if m:
            flush()
            level = len(m.group(1))
            if level == 1 and not model["title"]:
                model["title"] = clean(m.group(2))
            else:
                sec = {"heading": clean(m.group(2)), "level": max(1, level - 1), "blocks": []}
                model["sections"].append(sec)
        elif img:
            flush()
            p = Path(img.group(2))
            cand = [src.parent / p, p]
            found = next((c for c in cand if c.exists()), None)
            if not found:
                missing.append(img.group(2))
            path = (found or cand[0]).as_posix()
            sec["blocks"].append({"type": "image", "path": path, "caption": clean(img.group(1)), "width_cm": a.image_width})
        elif re.match(r"^\s*[-*]\s+", line):
            flush()
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(clean(re.sub(r"^\s*[-*]\s+", "", lines[i])))
                i += 1
            sec["blocks"].append({"type": "bullets", "items": items})
            continue
        elif re.match(r"^\s*\d+[.)]\s+", line):
            flush()
            # keep the markdown's own numbers: Word's auto-numbering would continue across sections
            while i < len(lines) and re.match(r"^\s*\d+[.)]\s+", lines[i]):
                num, text = re.match(r"^\s*(\d+)[.)]\s+(.*)$", lines[i]).groups()
                sec["blocks"].append({"type": "paragraph", "text": f"{num}. {clean(text)}"})
                i += 1
            continue
        elif line.strip().startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [clean(c) for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                sec["blocks"].append({"type": "table", "columns": rows[0], "rows": rows[1:]})
            continue
        elif line.strip() == "---":
            flush()
            sec["blocks"].append({"type": "page_break"})
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
        i += 1
    flush()
    model["sections"] = [s for s in model["sections"] if s["heading"] or s["blocks"]]
    if not model["title"]:
        model["title"] = src.stem
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(model, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {a.out} ({len(model['sections'])} sections)")
    for mi in missing:
        print(f"warning: image not found: {mi}", file=sys.stderr)


if __name__ == "__main__":
    main()
