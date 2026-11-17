# /// script
# requires-python = ">=3.10"
# dependencies = ["pdfplumber==0.11.10"]
# ///
"""Convert a PDF spec to markdown with page markers, so reviewers can cite "<file>.pdf p.3".

    uv run pdf_to_md.py spec.pdf qa/specs/PROJ-123/sources/spec.md

Each page becomes "## Page N" with its text, then its tables as markdown tables.
Pages with (almost) no text are probably scanned images: they are listed on stderr and in
the output, and the exit code stays 0. Render those pages to images (pdf skill:
scripts/convert_pdf_to_images.py) and read them visually, or OCR them as the pdf skill says.
"""
import sys
from pathlib import Path

import pdfplumber


def cell(v):
    return " ".join(str(v or "").split()).replace("|", "\\|")


def table_md(rows):
    rows = [r for r in rows if r and any(c not in (None, "") for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [[cell(c) for c in r] + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def main():
    if len(sys.argv) != 3 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if len(sys.argv) == 2 else 1)
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    if not src.is_file():
        print(f"error: not a file: {src}", file=sys.stderr)
        sys.exit(1)
    parts = [f"# {src.name}", "", f"Converted from `{src}` by pdf_to_md.py. Cite as `{src.name} p.<N>`.", ""]
    scanned = []
    try:
        with pdfplumber.open(str(src)) as pdf:
            if pdf.metadata.get("Title"):
                parts += [f"- PDF title: {pdf.metadata['Title']}", ""]
            for n, page in enumerate(pdf.pages, 1):
                text = (page.extract_text() or "").strip()
                parts += [f"## Page {n}", ""]
                if len(text) < 20:
                    scanned.append(n)
                    parts += ["_(no text layer: scanned page, read the page image)_", ""]
                else:
                    parts += [text, ""]
                for i, t in enumerate(page.extract_tables() or [], 1):
                    md = table_md(t)
                    if md:
                        parts += [f"Table {n}.{i}:", "", md, ""]
    except Exception as e:  # noqa: BLE001 — encrypted or broken PDFs
        print(f"error: cannot read {src}: {e}", file=sys.stderr)
        sys.exit(1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {out}")
    if scanned:
        print(f"warning: pages without text (scanned?): {', '.join(map(str, scanned))}", file=sys.stderr)


if __name__ == "__main__":
    main()
