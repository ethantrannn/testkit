# Visual comparison

Pixel comparison of a screen against an approved image: the previous release's screenshot (regression) or the design frame exported from Figma (design parity). `scripts/visual_diff.py` (Pillow 13.0.0, run with `uv run`) writes a three-panel diff image and a mismatch percentage.

## 1. Baselines

- Stored in `qa/baselines/<screen>@<W>x<H>.png` (CSS viewport size in the name, e.g. `checkout@1280x720.png`, `checkout@375x812.png`). Commit them; they are shared across runs.
- A baseline is approved by a person. Create one with `--init` the first time (the run reports `BASELINE_CREATED`) and ask the lead/user to look at it before it counts. Update a baseline only when the change is an intended, accepted design change; note the ticket in the commit message.
- Same capture conditions every time: same viewport and `deviceScaleFactor`, same test data, logged-in state, fonts loaded (`wait_for_network_idle()`), animations finished, caret hidden, scroll at top.

## 2. Capture the current screenshot

```bash
$BU run PROJ-123-VIS <<'PY'
import os
os.makedirs("qa/runs/PROJ-123/audits/visual", exist_ok=True)       # capture_screenshot does not create folders
cdp("Emulation.setDeviceMetricsOverride", width=375, height=812, deviceScaleFactor=2, mobile=True)
goto_url("https://staging.example.com/checkout"); wait_for_load(); wait_for_network_idle()
js("document.querySelectorAll('*').forEach(e => e.style.caretColor = 'transparent'); document.getAnimations().forEach(a => a.finish()); true")
capture_screenshot("qa/runs/PROJ-123/audits/visual/checkout@375x812.png")   # add full=True for the whole page
cdp("Emulation.clearDeviceMetricsOverride")
PY
```

Look at the screenshot before comparing: a cookie banner or a spinner makes every diff fail.

## 3. Compare

```bash
V=qa/runs/PROJ-123/audits/visual
uv run $QA/visual_diff.py qa/baselines/checkout@375x812.png $V/checkout@375x812.png \
  --out $V/checkout@375x812-diff.png --json $V/checkout@375x812-diff.json \
  --threshold 0.01 --tolerance 16 --mask 0,0,750,88      # mask: X,Y,W,H in image pixels (status bar, clock, avatar)
```

| Option | Use |
|---|---|
| `--threshold PCT` | max changed pixels in percent that still passes (config `audits.visual.threshold_pct`, default 0.01). A one-word copy change is about 0.05% of a phone screenshot, so keep it low and read the regions |
| `--tolerance N` | colour distance 0–255 treated as equal; raise to 30–40 for Figma vs browser (font rendering differs) |
| `--mask X,Y,W,H` | ignore dynamic regions; repeatable; image pixels (CSS px × deviceScaleFactor) |
| `--fit` | resize current to baseline size (Figma export at another scale); without it a size mismatch fails |
| `--init` | create the baseline from the current image when it does not exist |

Exit 0 = PASS (or baseline created), 1 = FAIL, 2 = input error. JSON: `mismatch_pct`, `changed_pixels`, `regions` (boxes `[x, y, w, h]`, largest first), `verdict`.

**Open the diff image and look at it.** Left = baseline, middle = current, right = current faded with changed pixels in red and changed regions boxed. Decide per region: intended change (ticket says so) → not a bug, propose a baseline update; unintended → bug with the diff image as evidence; noise (anti-aliasing) → raise tolerance or mask, rerun.

## 4. Figma frame as the baseline

When the ticket links a Figma design and Figma tools are available in this session (an MCP server that exports nodes or takes node screenshots), export the frame that matches the screen:

1. Get the file key and node id from the link (`figma.com/design/<FILE_KEY>/...?node-id=12-345` → node `12:345`).
2. Export as PNG at the same scale as the screenshot (`deviceScaleFactor`, usually 2 for mobile, 1 for desktop) and save it as `qa/baselines/<screen>@<W>x<H>.figma.png`.
3. Without MCP tools, the REST API works with a personal token in an environment variable (never in files): `curl -s -H "X-Figma-Token: $FIGMA_TOKEN" "https://api.figma.com/v1/images/<FILE_KEY>?ids=12:345&format=png&scale=2"` returns `{"images": {"12:345": "<temporary url>"}}`; download that URL. Ask the user for the token variable name; do not ask for the token itself.
4. Compare with `--fit --tolerance 40` and mask areas filled with real data (names, prices, dates) that the design shows as placeholders.

Design parity findings are mostly `minor`/`trivial` (spacing, colour, font) unless an element is missing or the layout breaks; check the design is the approved, final version before filing.

## 5. Summary rows

`VIS-<screen>@<WxH>` | baseline (release or Figma) | mismatch % | threshold | regions | verdict | severity | diff PNG path, with one sentence describing each unintended region.
