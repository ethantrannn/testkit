---
name: testkit-guide
description: End-user documentation produced by walking the real product in a browser — step-by-step user guides with annotated screenshots (red box + step number), release notes for a version from tickets and run reports (New / Improved / Fixed / Known issues), FAQ and help articles, and video walkthroughs (MP4 slideshow with captions, or a browser-use recording). Renders markdown, Word (.docx) and PDF when LibreOffice exists. Use when the user asks for a user guide, manual, how-to, release notes, changelog for users, FAQ, help article, tutorial video, "hướng dẫn sử dụng", "tài liệu người dùng", "release note", "video hướng dẫn".
argument-hint: "guide <name> <flows | ticket> | release-notes <version> <tickets…> | faq <name> | video <name>"
---

# testkit guide (user documentation)

Documentation written from the product as it really behaves, not from the spec. You drive the app, capture each step, annotate the screenshots, and write in plain user language. Read `references/doc-templates.md` before writing any document and `references/capture-and-video.md` before capturing.

```bash
SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)   # the skills folder testkit installed into
BU=$SK/browser-testing/scripts/bu-session.sh
```

Outputs go to `qa/guides/<name>/` (guides, FAQ, videos) and `qa/releases/<version>/release-notes.md`. Language: `project.language` in `qa/config.yml`; use the app's on-screen labels exactly.

## 1. Inputs

- **Flows** to document: from the user, or from a ticket's ACs (`qa/runs/<RUN_ID>/plan.md`) turned into user tasks ("Sign in", "Add a note"). Confirm the list and the audience (end user, admin) when it is not obvious.
- **Environment**: an environment from `qa/config.yml` (prefer staging/demo; never production with real data). Account: a demo/test account from `qa/accounts.local.json` with a neutral name and email, because it will appear in screenshots.
- Existing material worth reading: run reports, cases (their steps are a good skeleton, but the guide is written for users, not testers), bug files for known issues.

## 2. User guide

1. **Walk each flow once without capturing** (session `guide-<name>`, see the `browser-testing` skill) to learn the real labels and the shortest path. Note anything that blocks the flow; a broken flow is a bug to report, not something to document around.
2. **Capture**: run the flow again with the helpers in `scripts/guide_capture.py` — for each step, `gd_box(role=…, name=…)` (accessibility tree → `DOM.getBoxModel`) or `gd_box(selector=…)`, then `gd_step(G, n, caption, [box], flow=…)` *before* the action, then the action (`gd_click(box)`, `type_text`, …). This writes `raw/<flow>-NN.png` and `steps.json`. Snippet and details: `references/capture-and-video.md`. Stop the session at the end (`$BU stop guide-<name>`).
3. **Look at every raw screenshot.** Re-capture steps where the page was still loading, a toast covers the target, or personal data is visible.
4. **Annotate**:
   ```bash
   uv run $SK/testkit-guide/scripts/annotate.py --steps qa/guides/<name>/steps.json --crop 120 --out-dir doc-img
   ```
   Open the annotated images: the red box must sit on the control the step names, the badge number must match the step.
5. **Write** `qa/guides/<name>/guide.md` with the guide template in `references/doc-templates.md`: task-oriented title, "Before you start", one section per flow, numbered steps in user language each followed by its image `![Step N — …](doc-img/<flow>-NN.png)`, troubleshooting lines for errors you saw, "Good to know".
6. **Render Word** (and PDF):
   ```bash
   python3 $SK/testkit-guide/scripts/md_to_docx_model.py qa/guides/<name>/guide.md qa/guides/<name>/guide-docx.json \
     --meta "Product=<name>" --meta "Version=<version>" --image-width 12
   uv run $SK/testkit-export/scripts/build_docx_report.py qa/guides/<name>/guide-docx.json qa/guides/<name>/<name>.docx
   uv run --with lxml --with defusedxml python $SK/docx/scripts/office/validate.py qa/guides/<name>/<name>.docx
   ```
   PDF only when LibreOffice exists: `uv run --with lxml --with defusedxml python $SK/docx/scripts/office/soffice.py --headless --convert-to pdf --outdir qa/guides/<name> qa/guides/<name>/<name>.docx`. Check visually as in the `testkit-export` skill (PDF pages via `pdftoppm`, or `qlmanage -t -s 1400` for page one on macOS).

## 3. Release notes

For a version: the list of tickets (from the user, the tracker, or a `qa/releases/<version>/` plan), their run reports and verdicts, and bugs (`qa/bugs/*.md`). Write `qa/releases/<version>/release-notes.md` with the release-notes template: grouped **New / Improved / Fixed / Known issues**, user-facing language, no internal IDs unless asked. Only `verified` bugs go under Fixed; open bugs a user can hit go under Known issues with the workaround; never publish security issues; ask about tickets whose verdict is `NOT READY`. Screenshots are optional (capture new screens as in section 2). Render Word with `md_to_docx_model.py` + `build_docx_report.py` as above.

## 4. FAQ and help articles

From the guide's troubleshooting lines, known issues with workarounds, error messages seen in runs, and answered `Questions` in results files. Write `qa/guides/<name>/faq.md` (and `articles/<slug>.md` for single in-depth tasks) with the FAQ template. Verify every answer in the product (or cite the run that showed it); an answer you could not check is a question for the user. Render to Word the same way when asked.

## 5. Video walkthrough

- **Slideshow (default)** from the guide's steps — annotated full-screen frames with captions:
  ```bash
  uv run $SK/testkit-guide/scripts/annotate.py --steps qa/guides/<name>/steps.json --dim
  uv run $SK/testkit-guide/scripts/slideshow.py qa/guides/<name>/steps.json qa/guides/<name>/<name>.mp4 \
    --title "<guide title>" --subtitle "<product version>"
  ```
  1920×1080 H.264 MP4, title card, one slide per step with its number and caption. Needs ffmpeg.
- **Recorded session**: wrap the capture run in `start_recording("<name>", title=…)` / `stop_recording()` and turn it into an animated video with `browser-use video init/review/export` and an edit brief (redact personal data). Steps in `references/capture-and-video.md`.

Check every video: `ffprobe` for duration and size, extract 2–3 frames with ffmpeg and look at them (caption readable, box on the right control, no personal data). Remove `<name>.frames/` when done.

## 6. Report back

Paths of `guide.md`, `.docx` (and `.pdf`), annotated images, `.mp4`, release notes or FAQ; the flows covered; steps you could not document and why (bugs found while walking go to the `bug-reporting` flow, with the user's agreement); whether screenshots show any personal data; which visual checks ran.

## Safety

- Only environments from `qa/config.yml`; prefer staging/demo data. Respect `allow_write: false`: flows that create or delete data cannot be captured there; say so.
- Never capture real customer data, secrets or password values. Use demo accounts; redact (or re-capture) any frame that shows personal data. Recordings keep typed text other than passwords in `events.jsonl`: do not share recording folders.
- Ask before publishing documents or videos anywhere outside the repo.
