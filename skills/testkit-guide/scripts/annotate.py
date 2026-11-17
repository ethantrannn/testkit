# /// script
# requires-python = ">=3.10"
# dependencies = ["Pillow==13.0.0"]
# ///
"""Draw red boxes and step-number badges on screenshots for user guides.

    uv run annotate.py shot.png boxes.json out.png [--label 3] [--scale 2] [--dim]
    uv run annotate.py --steps qa/guides/<NAME>/steps.json [--dim] [--crop 200] [--out-dir img]

Single image: boxes.json is a list of boxes, or {"boxes": [...], "scale": 2, "viewport": {"w": 1280}}.
A box is {"x": 450, "y": 156, "w": 380, "h": 37, "label": "1", "color": "E02424"} in CSS pixels of the
viewport (what getBoundingClientRect / DOM.getBoxModel return); label and color are optional. Boxes are
scaled to image pixels by --scale, else by image width / viewport.w, else 1 (devicePixelRatio).
--label puts that number on the first box that has none.

Steps mode: reads steps.json written by guide_capture.py's gd_step(), writes <guide>/img/<flow>-NN.png
for every step (badge = step number) and stores the path as "image" in steps.json.

--dim darkens everything outside the boxes slightly to draw the eye. --crop 200 keeps 200 CSS px of
context around the boxes (at least 720x400 CSS px) (good for documents; keep full frames for videos). Pillow pinned; any OS.
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RED = "E02424"
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def font(size):
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def annotate(src, boxes, out, scale=None, viewport_w=None, dim=False, crop=None):
    img = Image.open(src).convert("RGB")
    if scale is None:
        scale = img.width / viewport_w if viewport_w else 1.0
    u = max(1.0, img.width / 1280)  # stroke and badge size follow the image size
    pad, stroke, badge = 6 * u, max(3, round(3 * u)), round(34 * u)
    rects = []
    for b in boxes:
        x0, y0 = b["x"] * scale - pad, b["y"] * scale - pad
        x1, y1 = (b["x"] + b["w"]) * scale + pad, (b["y"] + b["h"]) * scale + pad
        x0, y0 = max(stroke, x0), max(stroke, y0)
        x1, y1 = min(img.width - stroke, x1), min(img.height - stroke, y1)
        rects.append((x0, y0, x1, y1, b))
    if dim and rects:
        shade = Image.new("L", img.size, 45)
        d = ImageDraw.Draw(shade)
        for x0, y0, x1, y1, _ in rects:
            d.rounded_rectangle((x0, y0, x1, y1), radius=8 * u, fill=0)
        img = Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, shade)
    draw = ImageDraw.Draw(img)
    f = font(round(badge * 0.6))
    for x0, y0, x1, y1, b in rects:
        color = hexrgb(b.get("color") or RED)
        draw.rounded_rectangle((x0, y0, x1, y1), radius=8 * u, outline=color, width=stroke)
        label = str(b.get("label") or "")
        if label:
            # badge left of the box, vertically centred (labels above the field stay readable);
            # on the box's top-left corner when there is no room on the left
            if x0 - badge - 6 * u >= 2:
                cx, cy = x0 - badge / 2 - 6 * u, (y0 + y1) / 2
            else:
                cx, cy = x0, y0
            cx = min(max(cx, badge / 2 + 2), img.width - badge / 2 - 2)
            cy = min(max(cy, badge / 2 + 2), img.height - badge / 2 - 2)
            draw.ellipse((cx - badge / 2, cy - badge / 2, cx + badge / 2, cy + badge / 2), fill=color,
                         outline=(255, 255, 255), width=max(2, round(2 * u)))
            draw.text((cx, cy), label, font=f, fill=(255, 255, 255), anchor="mm")
    if crop is not None and rects:
        m = crop * scale  # keep `crop` CSS px of context around all boxes, at least 720x400 CSS px
        x0, y0 = min(r[0] for r in rects) - m, min(r[1] for r in rects) - m
        x1, y1 = max(r[2] for r in rects) + m, max(r[3] for r in rects) + m
        for lo, hi, need, limit in ((0, 2, 720 * scale, img.width), (1, 3, 400 * scale, img.height)):
            box = [x0, y0, x1, y1]
            grow = max(0, need - (box[hi] - box[lo])) / 2
            box[lo], box[hi] = box[lo] - grow, box[hi] + grow
            if box[lo] < 0:
                box[hi], box[lo] = box[hi] - box[lo], 0
            if box[hi] > limit:
                box[lo], box[hi] = max(0, box[lo] - (box[hi] - limit)), limit
            x0, y0, x1, y1 = box
        img = img.crop((round(x0), round(y0), round(x1), round(y1)))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("shot", nargs="?")
    ap.add_argument("boxes", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--steps", help="steps.json from gd_step()")
    ap.add_argument("--out-dir", default="img", help="steps mode: folder next to steps.json (default img)")
    ap.add_argument("--label", help="number for the first unlabeled box")
    ap.add_argument("--scale", type=float, help="CSS px -> image px factor (devicePixelRatio)")
    ap.add_argument("--dim", action="store_true", help="darken outside the boxes")
    ap.add_argument("--crop", type=float, help="crop to the boxes plus this many CSS px of context (docs); omit for videos")
    a = ap.parse_args()

    if a.steps:
        sp = Path(a.steps)
        if not sp.exists():
            sys.exit(f"annotate: {sp} not found")
        data = json.loads(sp.read_text(encoding="utf-8"))
        out_dir = sp.parent / a.out_dir
        for s in data.get("steps", []):
            if not Path(s["shot"]).exists():
                sys.exit(f"annotate: screenshot {s['shot']} not found (paths are relative to the project root)")
            boxes = [dict(b, label=b.get("label") or (str(s["n"]) if i == 0 else "")) for i, b in enumerate(s.get("boxes", []))]
            vp = s.get("viewport") or {}
            out = out_dir / f"{s.get('flow', 'flow')}-{int(s['n']):02d}.png"
            annotate(s["shot"], boxes, out, scale=a.scale, viewport_w=vp.get("w"), dim=a.dim, crop=a.crop)
            s["image" if a.out_dir == "img" else f"image_{a.out_dir}"] = out.as_posix()
            print(f"wrote {out} ({len(boxes)} box(es))")
        sp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        return

    if not (a.shot and a.boxes and a.out):
        ap.error("give shot.png boxes.json out.png, or --steps steps.json")
    for p in (a.shot, a.boxes):
        if not Path(p).exists():
            sys.exit(f"annotate: {p} not found")
    spec = json.loads(Path(a.boxes).read_text(encoding="utf-8"))
    boxes = spec if isinstance(spec, list) else spec.get("boxes", [])
    scale = a.scale or (spec.get("scale") if isinstance(spec, dict) else None)
    vw = (spec.get("viewport") or {}).get("w") if isinstance(spec, dict) else None
    if a.label:
        for b in boxes:
            if not b.get("label"):
                b["label"] = a.label
                break
    print(f"wrote {annotate(a.shot, boxes, a.out, scale=scale, viewport_w=vw, dim=a.dim, crop=a.crop)}")


if __name__ == "__main__":
    main()
