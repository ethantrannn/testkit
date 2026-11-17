"""testkit-guide capture helpers for a browser-use session (browser-testing/scripts/bu-session.sh run).

Load them at the top of every snippet (each `run` is a fresh Python process):

    import os; exec(open(next(p for p in (".claude/skills", ".agents/skills", "skills") if os.path.isdir(p))
                    + "/testkit-guide/scripts/guide_capture.py").read())

    gd_box(selector=None, role=None, name=None)  -> {"x","y","w","h"} in CSS pixels of the viewport, or None.
        selector: CSS selector (document.querySelector). Otherwise role + accessible name from the
        accessibility tree (Accessibility.getFullAXTree -> backendDOMNodeId -> DOM.getBoxModel), which
        matches what the user sees ("button" "Sign in"). Scrolls the element into view first.
    gd_step(guide_dir, n, caption, boxes=None, flow=None)
        Screenshot of the current viewport to <guide_dir>/raw/<flow>-NN.png (taken BEFORE the action,
        so the element to click is visible) and append/replace step n in <guide_dir>/steps.json with the
        caption, the boxes (CSS px), devicePixelRatio and viewport size, so annotate.py can scale them.
    gd_click(box)  click the centre of a box (CSS px) like a user.

Only helpers that browser-use pre-imports are used here: js, cdp, capture_screenshot, click_at_xy.
"""
import json as _json
import os as _os


def gd_box(selector=None, role=None, name=None):
    if selector:
        r = js("(()=>{const e=document.querySelector(%s); if(!e) return null;"
               "e.scrollIntoView({block:'center', inline:'nearest'});"
               "const r=e.getBoundingClientRect(); return {x:r.x, y:r.y, w:r.width, h:r.height}})()"
               % _json.dumps(selector))
        return r
    if not role and not name:
        raise ValueError("gd_box: give a CSS selector, or role and/or name")
    nodes = cdp("Accessibility.getFullAXTree")["nodes"]
    for n in nodes:
        if n.get("ignored") or "backendDOMNodeId" not in n:
            continue
        if role and (n.get("role") or {}).get("value") != role:
            continue
        if name and ((n.get("name") or {}).get("value") or "").strip() != name:
            continue
        b = n["backendDOMNodeId"]
        try:
            cdp("DOM.scrollIntoViewIfNeeded", backendNodeId=b)
        except Exception:
            pass
        q = cdp("DOM.getBoxModel", backendNodeId=b)["model"]["border"]  # 8 numbers: x1,y1 .. x4,y4 (viewport CSS px)
        xs, ys = q[0::2], q[1::2]
        return {"x": min(xs), "y": min(ys), "w": max(xs) - min(xs), "h": max(ys) - min(ys)}
    return None


def gd_click(box):
    click_at_xy(box["x"] + box["w"] / 2, box["y"] + box["h"] / 2)


def gd_step(guide_dir, n, caption, boxes=None, flow="flow"):
    raw = _os.path.join(guide_dir, "raw")
    _os.makedirs(raw, exist_ok=True)
    shot = _os.path.join(raw, f"{flow}-{int(n):02d}.png")
    capture_screenshot(shot)
    view = js("({w: innerWidth, h: innerHeight, dpr: devicePixelRatio, url: location.pathname})")
    path = _os.path.join(guide_dir, "steps.json")
    data = _json.load(open(path, encoding="utf-8")) if _os.path.exists(path) else {"steps": []}
    data["steps"] = [s for s in data["steps"] if not (s.get("flow") == flow and s.get("n") == int(n))]
    data["steps"].append({"flow": flow, "n": int(n), "caption": caption, "shot": shot,
                          "boxes": [b for b in (boxes or []) if b], "viewport": view})
    order = list(dict.fromkeys(s.get("flow") for s in data["steps"]))  # flows keep their first-seen order
    data["steps"].sort(key=lambda s: (order.index(s.get("flow")), s["n"]))
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(data, f, indent=1, ensure_ascii=False)
    return {"shot": shot, "boxes": len(boxes or []), "viewport": view}
