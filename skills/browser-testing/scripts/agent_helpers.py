"""testkit evidence helpers for browser-use.

bu-session.sh copies this file into BH_AGENT_WORKSPACE, and browser-use pre-imports every
public name here next to its own helpers (new_tab, page_info, js, capture_screenshot, ...).

    tk_clear()                                  forget console/network events seen so far (start of a case)
    tk_problems()                               console errors, JS exceptions, HTTP >= 400, failed requests since last drain
    tk_evidence("qa/runs/R/evidence/S1/TC-S1-001-step3")
        -> saves <base>.png and, when there are problems, <base>.json; returns a short summary dict
"""
import json
import os

from browser_harness.helpers import capture_screenshot, drain_events, page_info


def tk_clear():
    """Drop buffered CDP events so the next tk_problems() covers only the current case."""
    drain_events()


def _arg_text(a):
    return str(a.get("value", a.get("description", a.get("type", ""))))


def tk_problems(events=None):
    """Return problems from drained CDP events: console errors, exceptions, HTTP >= 400, failed loads."""
    evs = drain_events() if events is None else events
    out = []
    for e in evs:
        m, p = e.get("method"), e.get("params", {})
        if m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            out.append({"kind": "exception", "text": (d.get("exception") or {}).get("description") or d.get("text")})
        elif m == "Runtime.consoleAPICalled" and p.get("type") == "error":
            out.append({"kind": "console", "text": " ".join(_arg_text(a) for a in p.get("args", []))})
        elif m == "Network.responseReceived" and p.get("response", {}).get("status", 0) >= 400:
            r = p["response"]
            out.append({"kind": "http", "status": r.get("status"), "method": p.get("type"), "url": r.get("url")})
        elif m == "Network.loadingFailed" and not p.get("canceled"):
            out.append({"kind": "network", "text": p.get("errorText"), "type": p.get("type")})
    return out


def tk_evidence(path_base, full=False):
    """Screenshot to <path_base>.png; write problems since the last drain to <path_base>.json if any."""
    os.makedirs(os.path.dirname(path_base) or ".", exist_ok=True)
    shot = capture_screenshot(path_base + ".png", full=full)
    probs = tk_problems()
    info = page_info()
    if probs:
        with open(path_base + ".json", "w", encoding="utf-8") as f:
            json.dump({"url": info.get("url"), "title": info.get("title"), "problems": probs}, f, indent=2, ensure_ascii=False)
    return {"screenshot": shot, "url": info.get("url"), "problems": len(probs),
            "problems_file": (path_base + ".json") if probs else None}
