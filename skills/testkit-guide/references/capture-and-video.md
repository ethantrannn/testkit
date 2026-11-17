# Capturing steps and making videos

## Contents
- Capture snippet (browser-use)
- Getting element boxes by hand
- steps.json format
- Annotating
- Video A: slideshow from step screenshots (ffmpeg)
- Video B: browser-use recording → native video
- agent-browser and MCP browsers

## Capture snippet (browser-use)

Each `bu-session.sh run` is a new Python process with browser-use helpers pre-imported; load the guide helpers at the top of every snippet. Take the screenshot **before** the action, so the element to click is visible and boxed.

```bash
SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)
BU=$SK/browser-testing/scripts/bu-session.sh
$BU run guide-getting-started <<'PY'
import os; exec(open(next(p for p in (".claude/skills", ".agents/skills") if os.path.isdir(p)) + "/testkit-guide/scripts/guide_capture.py").read())
G = "qa/guides/getting-started"
new_tab("https://staging.example.com/login"); wait_for_load()

b = gd_box(role="textbox", name="Email")            # accessibility tree: role + visible name
gd_step(G, 1, "Type your email address in the Email box.", [b], flow="sign-in")
gd_click(b); type_text("demo@example.test")

b = gd_box(role="button", name="Sign in")
gd_step(G, 2, "Click Sign in.", [b], flow="sign-in")
gd_click(b); wait_for_load()

b = gd_box(selector="[data-testid=account-menu]")   # or a CSS selector
gd_step(G, 3, "Your name appears at the top right.", [b], flow="sign-in")
PY
$BU stop guide-getting-started
```

`gd_box` returns `None` when nothing matches: print the AX tree filtered by role to find the real name (`[ (n["role"]["value"], n.get("name",{}).get("value")) for n in cdp("Accessibility.getFullAXTree")["nodes"] if n.get("role",{}).get("value") in ("button","link","textbox") ]`). Open the raw screenshot of every step and look at it before annotating.

For a mobile guide, set the viewport first: `cdp("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=3, mobile=True)`; boxes stay in CSS px and `annotate.py` scales them by image width / viewport width (here ×3).

## Getting element boxes by hand

What `gd_box` does, if you need it inline:

```python
nodes = cdp("Accessibility.getFullAXTree")["nodes"]
n = next(n for n in nodes if n.get("role", {}).get("value") == "button" and n.get("name", {}).get("value") == "Sign in")
cdp("DOM.scrollIntoViewIfNeeded", backendNodeId=n["backendDOMNodeId"])
q = cdp("DOM.getBoxModel", backendNodeId=n["backendDOMNodeId"])["model"]["border"]   # x1,y1,x2,y2,x3,y3,x4,y4
box = {"x": min(q[0::2]), "y": min(q[1::2]), "w": max(q[0::2]) - min(q[0::2]), "h": max(q[1::2]) - min(q[1::2])}
# or for a CSS selector:
box = js("(()=>{const r=document.querySelector('#email').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})()")
dpr = js("devicePixelRatio")      # screenshot pixels = CSS pixels × dpr
```

`DOM.getBoxModel` quads and `getBoundingClientRect` are viewport CSS pixels (after scrolling), the same space as `click_at_xy`. Take the screenshot right after measuring, without scrolling in between.

## steps.json format

```json
{
  "titles": {"sign-in": "Sign in"},
  "steps": [
    {"flow": "sign-in", "n": 1, "caption": "Type your email address in the Email box.",
     "shot": "qa/guides/getting-started/raw/sign-in-01.png",
     "boxes": [{"x": 450, "y": 156, "w": 380, "h": 37}],
     "viewport": {"w": 1280, "h": 633, "dpr": 1, "url": "/"},
     "image": "qa/guides/getting-started/img/sign-in-01.png"}
  ]
}
```

`gd_step` writes everything except `image` (added by `annotate.py --steps`). You may edit captions, add a second box to a step (`{"x":…, "label": "2"}` for a two-part step), or delete steps before annotating. Paths are relative to the project root.

## Annotating

```bash
uv run $SK/testkit-guide/scripts/annotate.py --steps qa/guides/<NAME>/steps.json --crop 120 --out-dir doc-img   # documents
uv run $SK/testkit-guide/scripts/annotate.py --steps qa/guides/<NAME>/steps.json --dim                         # video frames (full screen)
uv run $SK/testkit-guide/scripts/annotate.py shot.png boxes.json out.png --label 3                               # one image
```

Red rounded box (6 px padding) around each element; a numbered red badge left of the first box (on its corner when there is no room). `--crop` keeps context around the boxes (at least 720×400 CSS px) so documents stay readable; `--dim` darkens the rest of the screen. Open the annotated images and check the box sits on the right control.

## Video A: slideshow from step screenshots (ffmpeg)

```bash
uv run $SK/testkit-guide/scripts/slideshow.py qa/guides/<NAME>/steps.json qa/guides/<NAME>/<NAME>.mp4 \
  --title "Getting started with Acme Notes" --subtitle "Version 2.3" [--flow sign-in] [--seconds auto]
```

1920×1080 H.264 (yuv420p, faststart), title card, then one slide per step: annotated screenshot above a caption band with the step number. Duration auto = 2.5 s + 0.3 s per caption word (max 8 s). Check it: `ffprobe -v error -show_entries format=duration -of compact <mp4>` and extract 2–3 frames (`ffmpeg -v error -ss 5 -i <mp4> -frames:v 1 frame.png`), then look at them. Delete `<NAME>.frames/` afterwards.

Use this for documentation videos: deterministic, works with any browser tool, no extra services.

## Video B: browser-use recording → native video

browser-use 1.x records a session as frames: `start_recording(name, title=...)` before the flow, `stop_recording()` after; it returns the folder `qa/.browser-use/workspace/recordings/<name>/` with `meta.json`, `events.jsonl` (one line per action with the focused element's box; password fields are masked, other typed text is stored) and `0001.jpg …`. The `browser-use video` command turns it into an animated MP4 (cursor motion, zoom, chapter bar, captions):

```bash
REC=qa/.browser-use/workspace/recordings/<name>
browser-use video init $REC --require-explicit       # writes recording-summary.json (numbered events)
# write $REC/edit-brief.json (format: https://github.com/browser-use/browser-harness/blob/main/interaction-skills/make-video.md)
browser-use video review $REC                        # needs a browser; see below
browser-use video export $REC --reviewed             # → $REC/video.mp4 (never overwrites; --output v2.mp4)
```

- The brief lists `plan` chapters and `actions` (`event`, `afterEvent`, `chapter`, `route`, optional `label`, sticky `narration` ≤ 7 words set only when the thought changes), `outcomes`, and `privacy.reviewedFrames` + `privacy.redact` rectangles (page CSS px) for every used frame. Redact emails, names and any personal data; inspect `video-review-contact-sheet.jpg` and `.privacy-review/` before export.
- `review`/`export` render in Chrome through the browser-use daemon. In testkit run them bound to an isolated session: `$BU start video-render`, then with the port from `qa/.browser-use/sessions/video-render.env`: `BU_NAME=tk-video-render BU_CDP_URL=http://127.0.0.1:<PORT> browser-use video review $REC` (on macOS also `BH_RUNTIME_DIR=/tmp/tk-$(id -u)` when the home path is long), and `$BU stop video-render` afterwards. Without that it tries to attach to the user's own Chrome.
- Output is about 15–30 s and paced for a demo, not for step-by-step teaching; prefer Video A for guides and Video B for short "what's new" clips.

## agent-browser and MCP browsers

Same flow: get the element's box (agent-browser: `eval` with `getBoundingClientRect`; Playwright/DevTools MCP: evaluate the same script), screenshot before the action, and write `steps.json` by hand in the format above. `annotate.py` and `slideshow.py` do not depend on the browser tool.
