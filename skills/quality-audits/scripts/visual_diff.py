# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow==13.0.0"]
# ///
"""Compare two screenshots (baseline vs current, or a Figma export vs a screenshot).

    uv run visual_diff.py BASELINE.png CURRENT.png --out DIFF.png [options]

Options:
  --threshold PCT     max share of changed pixels, in percent, that still passes (default 0.01)
  --tolerance N       per-pixel colour distance 0-255 below which pixels count as equal (default 16;
                      absorbs anti-aliasing and JPEG/scaling noise)
  --mask X,Y,W,H      region to ignore (dynamic content: clock, avatar, ad); repeatable; baseline pixels
  --fit               resize CURRENT to BASELINE size first (Figma 2x exports, retina screenshots);
                      without it, a size mismatch fails
  --init              when BASELINE does not exist, copy CURRENT there and exit 0 ("baseline created")
  --json OUT.json     also write the result as JSON

Output: DIFF.png = baseline | current | highlight (changed pixels red over a faded current, changed
regions boxed). Prints a JSON result with mismatch_pct, changed_pixels, regions and verdict.
Exit codes: 0 PASS (or baseline created), 1 FAIL (over threshold or size mismatch), 2 usage/input error.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

CELL = 8  # grid cell size (px) used to group changed pixels into regions


def box(s):
    try:
        x, y, w, h = (int(v) for v in s.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(f"mask must be X,Y,W,H in pixels, got '{s}'")
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError(f"mask width and height must be > 0: '{s}'")
    return x, y, w, h


def regions(mask):
    """Group changed pixels into boxes: mark CELLxCELL cells with any change, flood-fill neighbours."""
    w, h = mask.size
    gw, gh = (w + CELL - 1) // CELL, (h + CELL - 1) // CELL
    small = mask.resize((gw, gh), Image.Resampling.BOX)  # any change in a cell -> value > 0
    px = small.load()
    seen, out = set(), []
    for gy in range(gh):
        for gx in range(gw):
            if px[gx, gy] == 0 or (gx, gy) in seen:
                continue
            stack, x0, y0, x1, y1 = [(gx, gy)], gx, gy, gx, gy
            seen.add((gx, gy))
            while stack:
                cx, cy = stack.pop()
                x0, y0, x1, y1 = min(x0, cx), min(y0, cy), max(x1, cx), max(y1, cy)
                for nx in range(cx - 1, cx + 2):
                    for ny in range(cy - 1, cy + 2):
                        if 0 <= nx < gw and 0 <= ny < gh and (nx, ny) not in seen and px[nx, ny] > 0:
                            seen.add((nx, ny))
                            stack.append((nx, ny))
            out.append([x0 * CELL, y0 * CELL, min(w, (x1 + 1) * CELL) - x0 * CELL, min(h, (y1 + 1) * CELL) - y0 * CELL])
    out.sort(key=lambda b: -b[2] * b[3])
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                epilog=__doc__.split("\n\n", 1)[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("baseline")
    p.add_argument("current")
    p.add_argument("--out", required=True, help="diff image to write (.png)")
    p.add_argument("--threshold", type=float, default=0.01)
    p.add_argument("--tolerance", type=int, default=16)
    p.add_argument("--mask", type=box, action="append", default=[])
    p.add_argument("--fit", action="store_true")
    p.add_argument("--init", action="store_true")
    p.add_argument("--json")
    a = p.parse_args()

    base_p, cur_p = Path(a.baseline), Path(a.current)
    if not cur_p.is_file():
        print(f"visual_diff: current image not found: {cur_p}", file=sys.stderr)
        return 2
    if not base_p.is_file():
        if a.init:
            base_p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cur_p, base_p)
            print(json.dumps({"verdict": "BASELINE_CREATED", "baseline": str(base_p)}))
            return 0
        print(f"visual_diff: baseline not found: {base_p} (use --init to create it from the current image)", file=sys.stderr)
        return 2
    try:
        base = Image.open(base_p).convert("RGB")
        cur = Image.open(cur_p).convert("RGB")
    except Exception as e:
        print(f"visual_diff: cannot open image: {e}", file=sys.stderr)
        return 2

    result = {"baseline": str(base_p), "current": str(cur_p), "diff": a.out, "baseline_size": list(base.size),
              "current_size": list(cur.size), "threshold_pct": a.threshold, "tolerance": a.tolerance,
              "masks": [list(m) for m in a.mask]}
    if base.size != cur.size:
        if not a.fit:
            result.update(verdict="FAIL", reason="size mismatch (use --fit for exports at another scale)")
            print(json.dumps(result, indent=2))
            _write(a.json, result)
            return 1
        cur = cur.resize(base.size, Image.Resampling.LANCZOS)
        result["fitted"] = True

    diff = ImageChops.difference(base, cur)
    # colour distance = max channel difference; pixels within tolerance count as equal
    dist = diff.split()
    mx = ImageChops.lighter(ImageChops.lighter(dist[0], dist[1]), dist[2])
    changed = mx.point(lambda v: 255 if v > a.tolerance else 0)
    if a.mask:
        d = ImageDraw.Draw(changed)
        for x, y, w, h in a.mask:
            d.rectangle([x, y, x + w - 1, y + h - 1], fill=0)
    total = base.size[0] * base.size[1]
    n = changed.histogram()[255]
    pct = 100.0 * n / total
    boxes = regions(changed)

    # highlight panel: faded current + red changed pixels + boxes; masks in grey
    faded = Image.blend(cur, Image.new("RGB", cur.size, "white"), 0.6)
    faded.paste(Image.new("RGB", cur.size, (230, 0, 0)), mask=changed)
    d = ImageDraw.Draw(faded)
    for x, y, w, h in boxes[:50]:
        d.rectangle([x - 2, y - 2, x + w + 1, y + h + 1], outline=(255, 0, 180), width=2)
    for x, y, w, h in a.mask:
        d.rectangle([x, y, x + w - 1, y + h - 1], outline=(120, 120, 120), width=2)
    W, H = base.size
    sheet = Image.new("RGB", (W * 3 + 20, H), "white")
    sheet.paste(base, (0, 0))
    sheet.paste(cur, (W + 10, 0))
    sheet.paste(faded, (2 * W + 20, 0))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(a.out)

    result.update(changed_pixels=n, total_pixels=total, mismatch_pct=round(pct, 4), regions=boxes[:20],
                  region_count=len(boxes), verdict="PASS" if pct <= a.threshold else "FAIL")
    print(json.dumps(result, indent=2))
    _write(a.json, result)
    return 0 if result["verdict"] == "PASS" else 1


def _write(path, data):
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
