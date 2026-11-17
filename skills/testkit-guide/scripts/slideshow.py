# /// script
# requires-python = ">=3.10"
# dependencies = ["Pillow==13.0.0"]
# ///
"""Turn guide steps (screenshots + captions) into an MP4 walkthrough with ffmpeg.

    uv run slideshow.py qa/guides/<NAME>/steps.json qa/guides/<NAME>/walkthrough.mp4 \
        [--title "Getting started"] [--subtitle "Acme Notes 2.3"] [--flow sign-in] [--size 1920x1080] \
        [--seconds auto|3.5] [--fps 30]

Each step becomes one slide: the annotated image ("image", else the raw "shot") fitted above a caption
band with the step number and caption. An optional title card comes first; when several flows are rendered,
a section card (steps.json "titles": {"<flow>": "Sign in"}, else the flow name) opens each flow. Duration per slide: --seconds,
or "auto" = 2.5 s + 0.3 s per word of the caption (max 8 s). Captions are drawn with Pillow (Vietnamese and
other non-Latin text work; no ffmpeg drawtext needed). Encodes H.264 yuv420p + faststart (plays everywhere).
Needs ffmpeg on PATH. Frames are kept in <out>.frames/ for checking; delete them when done.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG, BAND, TEXT, ACCENT, MUTED = (243, 245, 247), (255, 255, 255), (29, 39, 51), (224, 36, 36), (90, 102, 115)
FONTS = {
    "bold": ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
             "C:/Windows/Fonts/arialbd.ttf"],
    "regular": ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                "C:/Windows/Fonts/arial.ttf"],
}


def font(kind, size):
    for f in FONTS[kind]:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size)


def wrap(draw, text, f, width):
    lines, cur = [], ""
    for word in str(text).split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=f) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def slide(img_path, n, caption, size):
    W, H = size
    u = H / 1080
    band_h = round(200 * u)
    canvas = Image.new("RGB", (W, H), BG)
    shot = Image.open(img_path).convert("RGB")
    margin = round(40 * u)
    box_w, box_h = W - 2 * margin, H - band_h - 2 * margin
    k = min(box_w / shot.width, box_h / shot.height)  # fit, enlarging small screenshots too
    shot = shot.resize((round(shot.width * k), round(shot.height * k)), Image.LANCZOS)
    x, y = (W - shot.width) // 2, margin + (box_h - shot.height) // 2
    d = ImageDraw.Draw(canvas)
    d.rectangle((x - 1, y - 1, x + shot.width, y + shot.height), outline=(210, 216, 222), width=2)
    canvas.paste(shot, (x, y))
    d.rectangle((0, H - band_h, W, H), fill=BAND)
    r = round(42 * u)
    cx, cy = margin + r, H - band_h // 2
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ACCENT)
    d.text((cx, cy), str(n), font=font("bold", round(44 * u)), fill=(255, 255, 255), anchor="mm")
    f = font("regular", round(46 * u))
    tx = cx + r + round(36 * u)
    lines = wrap(d, caption, f, W - tx - margin)
    if len(lines) > 2:
        f = font("regular", round(38 * u))
        lines = wrap(d, caption, f, W - tx - margin)[:3]
    lh = f.size * 1.25
    ty = cy - lh * len(lines) / 2
    for i, line in enumerate(lines):
        d.text((tx, ty + i * lh), line, font=f, fill=TEXT)
    return canvas


def title_card(title, subtitle, size):
    W, H = size
    u = H / 1080
    c = Image.new("RGB", (W, H), (11, 60, 73))
    d = ImageDraw.Draw(c)
    f1, f2 = font("bold", round(84 * u)), font("regular", round(44 * u))
    lines = wrap(d, title, f1, W - round(240 * u))
    y = H / 2 - (len(lines) * f1.size * 1.2) / 2 - (30 * u if subtitle else 0)
    for i, line in enumerate(lines):
        d.text((W / 2, y + i * f1.size * 1.2), line, font=f1, fill=(255, 255, 255), anchor="mt")
    if subtitle:
        d.text((W / 2, y + len(lines) * f1.size * 1.2 + 30 * u), subtitle, font=f2, fill=(207, 227, 234), anchor="mt")
    return c


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("steps")
    ap.add_argument("out")
    ap.add_argument("--title")
    ap.add_argument("--subtitle")
    ap.add_argument("--flow", action="append", help="only these flows (repeatable); default all, in file order")
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--seconds", default="auto")
    ap.add_argument("--fps", type=int, default=30)
    a = ap.parse_args()

    ff = shutil.which("ffmpeg")
    if not ff:
        sys.exit("slideshow: ffmpeg not found (macOS: brew install ffmpeg · Linux: apt install ffmpeg · "
                 "Windows: winget install Gyan.FFmpeg)")
    sp = Path(a.steps)
    if not sp.exists():
        sys.exit(f"slideshow: {sp} not found")
    try:
        W, H = (int(v) for v in a.size.lower().split("x"))
    except ValueError:
        sys.exit("slideshow: --size must look like 1920x1080")
    W, H = W - W % 2, H - H % 2
    data = json.loads(sp.read_text(encoding="utf-8"))
    titles = data.get("titles") or {}
    steps = [s for s in data.get("steps", []) if not a.flow or s.get("flow") in a.flow]
    if not steps:
        sys.exit("slideshow: no steps to render")

    out = Path(a.out)
    frames = out.with_suffix(".frames")
    if frames.exists():
        shutil.rmtree(frames)
    frames.mkdir(parents=True)
    items = []
    if a.title:
        p = frames / "000-title.png"
        title_card(a.title, a.subtitle, (W, H)).save(p)
        items.append((p, 3.0))
    multi = len({s.get("flow") for s in steps}) > 1
    prev = None
    for i, s in enumerate(steps, 1):
        if multi and s.get("flow") != prev:  # section card between flows
            p = frames / f"{i:03d}-section.png"
            name = titles.get(s.get("flow")) or str(s.get("flow", "")).replace("-", " ").capitalize()
            title_card(name, a.title, (W, H)).save(p)
            items.append((p, 2.0))
        prev = s.get("flow")
        src = s.get("image") or s.get("shot")
        if not src or not Path(src).exists():
            sys.exit(f"slideshow: image for step {s.get('flow')} {s.get('n')} not found: {src}")
        p = frames / f"{i:03d}.png"
        slide(src, s["n"], s.get("caption", ""), (W, H)).save(p)
        sec = (min(8.0, 2.5 + 0.3 * len(str(s.get("caption", "")).split())) if a.seconds == "auto" else float(a.seconds))
        items.append((p, sec))
    lst = frames / "list.txt"
    body = "".join(f"file '{p.name}'\nduration {d:.2f}\n" for p, d in items)
    # the last file is listed twice (the concat demuxer drops the last duration); -t trims to the exact total
    lst.write_text(body + f"file '{items[-1][0].name}'\n", encoding="utf-8")
    total = sum(d for _, d in items)
    enc = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    codec = ["-c:v", "libx264", "-preset", "medium", "-crf", "20"] if "libx264" in enc else ["-c:v", "mpeg4", "-q:v", "3"]
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ff, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
           "-vf", f"fps={a.fps},format=yuv420p", "-t", f"{total:.2f}", *codec, "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd)
    if r.returncode:
        sys.exit(f"slideshow: ffmpeg failed ({r.returncode})")
    print(f"wrote {out} ({len(items)} slides, {total:.1f} s, {W}x{H}); frames in {frames}")


if __name__ == "__main__":
    main()
