# Accessibility audit

Automated scan with axe-core plus a keyboard-only walk. Automated tools find roughly a third to a half of WCAG problems; the keyboard walk and a short manual look cover the most common rest. Report what you checked and what you did not (screen reader, zoom 400%, captions) in `summary.md`.

## 1. axe-core scan

```bash
$BU run PROJ-123-A11Y <<'PY'
import glob; exec(open(glob.glob(".*/skills/quality-audits/scripts/browser_audits.py")[0]).read())
new_tab("https://staging.example.com/checkout"); wait_for_load(); wait_for_network_idle()
s = qa_axe("qa/runs/PROJ-123/audits/a11y/checkout",
           tags=["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],   # audits.a11y.tags
           disable_rules=[])                                     # audits.a11y.ignore_rules
print({k: s[k] for k in ("violations", "by_impact", "incomplete", "passes")})
for r in s["rules"]:
    print(r["impact"], r["severity"], r["rule"], r["nodes"], r["wcag"], r["targets"][:3], r["helpUrl"])
PY
```

- axe-core **4.14.0** is downloaded once from cdnjs (`https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.14.0/axe.min.js`, fallback jsdelivr), checked against its sha256 and cached in `qa/.cache/`. Offline machine: put the file at `qa/.cache/axe-core-4.14.0.min.js` yourself.
- Injection goes through CDP, so the page's CSP does not block it; the helper only bypasses CSP (and reloads) if `eval` is refused.
- Scope: `include=["main"]`, `exclude=["#chat-widget"]` (CSS selectors). Third-party widgets you do not own: exclude and mention them.
- Scan **each state** that matters, not only the first paint: open dialogs, expanded menus, form with validation errors shown, empty and error states. Call `qa_axe` again after each state change with a new base name (`checkout-errors`).
- Mobile layout: set the viewport (`browser-testing` section 2) and scan again (`checkout-mobile`).
- `incomplete` = axe could not decide (often contrast over images/gradients). Check those by eye; list them as "needs review", not as bugs, unless you confirm them.
- Same-origin iframes are not scanned by this helper; scan the iframe URL directly if it matters.

Raw file `<base>-axe.json`: `violations[].id`, `.impact`, `.help`, `.helpUrl`, `.tags` (WCAG success criteria like `wcag143`), `.nodes[].target` (selectors), `.nodes[].failureSummary` (what to fix). Quote the failure summary in the bug.

## 2. Keyboard-only and focus-visible

```bash
$BU run PROJ-123-A11Y <<'PY'
import glob; exec(open(glob.glob(".*/skills/quality-audits/scripts/browser_audits.py")[0]).read())
k = qa_keyboard("qa/runs/PROJ-123/audits/a11y/checkout", max_tabs=60)
print(k)
PY
```

The helper presses real Tab key events (keyboard modality, so `:focus-visible` styles apply) from the top of the page and records:

| Field | Meaning | Usually |
|---|---|---|
| `order` | focus stops as `tag[role] "name"` | compare with the visual reading order; a jump back to the header mid-form is a bug |
| `no_visible_focus` | stops where outline, box-shadow, border, background, colour and underline are all identical focused vs not | WCAG 2.4.7, major on primary controls; screenshots `<base>-nofocus-NN.png` |
| `possible_trap` | the same element took focus 3 times before the cycle completed | WCAG 2.1.2, critical |
| `clickable_not_focusable` | elements with `onclick` or a widget `role` that Tab never reaches | WCAG 2.1.1; critical when it is the only way to do the action |

Then check by hand, with `press_key("Enter")`, `press_key(" ")`, `press_key("Escape")`:

1. Every primary action on the screen can be completed with keyboard only (Enter on links/buttons, Space on checkboxes, arrows in radio groups, menus, tabs).
2. Opening a dialog moves focus into it; Tab stays inside; Escape closes it; focus returns to the trigger.
3. A "Skip to content" link exists on pages with long navigation (best practice, not a bug unless the docs require it).
4. Focus is never hidden behind sticky headers or cookie banners (look at the screenshot of that stop).

Open each `nofocus` screenshot: the helper compares computed styles, so a focus style drawn by a parent element (`:focus-within`) can be a false positive. Confirm visually before filing.

## 3. Quick manual checks worth five minutes

- Zoom: `cdp("Emulation.setDeviceMetricsOverride", width=320, height=720, deviceScaleFactor=1, mobile=True)` approximates 400% zoom on a 1280px screen: no horizontal scroll for text, nothing cut off (WCAG 1.4.10).
- Text spacing / reduced motion: `cdp("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])`; animations should stop or reduce.
- Forms: error messages are text (not colour only) and tied to the field (`aria-describedby`), required fields announced.
- Images that carry meaning have useful alt text (axe only checks that alt exists).

## 4. Summary rows

One row per rule per screen: `A11Y-<screen>-<rule>` | impact → severity | WCAG SC | nodes count | first selectors | `a11y/<screen>-axe.json`. Keyboard findings: `A11Y-<screen>-keyboard-<n>`.
