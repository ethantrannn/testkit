# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Risk matrix and effort estimate for a release test plan. Stdlib only.

    uv run estimate.py tickets.json estimate.md [--json estimate.json] [--lang vi|en]

tickets.json:
{
  "release": "2026.11",
  "assumptions": {                       # every key optional; defaults shown
    "hours_per_day": 6,
    "minutes_per_case": {"design": 10, "review": 3, "execute": 8},
    "retest_buffer": 0.2,                # share of execution time added for bug retests
    "regression_hours": 0,               # release-wide regression, not per ticket
    "uat_hours": 0,                      # QA support for UAT
    "default_size": {"high":   {"streams": 3, "cases_per_stream": 12},
                     "medium": {"streams": 2, "cases_per_stream": 8},
                     "low":    {"streams": 1, "cases_per_stream": 5}}
  },
  "tickets": [
    {"key": "PROJ-123", "title": "Mã giảm giá", "impact": 3, "likelihood": 2,
     "streams": 3, "cases": 41, "basis": "cases"},     # basis: cases | plan | estimate
    {"key": "PROJ-124", "title": "Đổi mật khẩu", "impact": "medium", "likelihood": "low"}
  ]
}

impact / likelihood: 1-3 or low|medium|high. Score = impact × likelihood; risk level:
high ≥ 6, medium 3-4, low ≤ 2. Missing streams/cases are filled from default_size of the
ticket's risk level (basis "estimate"). When "cases" is known it wins over streams × default.
"""
import argparse
import json
import sys
from pathlib import Path

LEVEL = {"low": 1, "medium": 2, "high": 3, 1: 1, 2: 2, 3: 3}
DEFAULTS = {
    "hours_per_day": 6,
    "minutes_per_case": {"design": 10, "review": 3, "execute": 8},
    "retest_buffer": 0.2,
    "regression_hours": 0,
    "uat_hours": 0,
    "default_size": {"high": {"streams": 3, "cases_per_stream": 12},
                     "medium": {"streams": 2, "cases_per_stream": 8},
                     "low": {"streams": 1, "cases_per_stream": 5}},
}
T = {
    "en": {"matrix": "Risk matrix (impact × likelihood)", "imp": "Impact", "lik": "Likelihood",
           "est": "Effort estimate", "key": "Ticket", "title": "Title", "score": "Score",
           "risk": "Risk", "streams": "Streams", "cases": "Cases", "basis": "Basis",
           "design": "Design h", "review": "Review h", "exec": "Execute h", "retest": "Retest h",
           "total": "Total h", "sum": "Total", "reg": "Release regression", "uat": "UAT support",
           "grand": "Grand total", "pd": "person-days", "day": "person-day", "ass": "Assumptions",
           "lv": {1: "low", 2: "medium", 3: "high"},
           "a_min": "- minutes per case: design {design}, review {review}, execute {execute}",
           "a_retest": "- retest buffer: {}% of execution time",
           "a_size": "- size when no plan exists (streams × cases per stream): ",
           "a_basis": "- basis: `cases` = counted in cases/*.md, `plan` = streams from plan.md, "
                      "`estimate` = default size for the risk level"},
    "vi": {"matrix": "Ma trận rủi ro (mức ảnh hưởng × khả năng xảy ra)", "imp": "Ảnh hưởng",
           "lik": "Khả năng", "est": "Ước lượng công sức", "key": "Ticket", "title": "Tiêu đề",
           "score": "Điểm", "risk": "Rủi ro", "streams": "Stream", "cases": "Case",
           "basis": "Cơ sở", "design": "Thiết kế (giờ)", "review": "Review (giờ)",
           "exec": "Thực thi (giờ)", "retest": "Retest (giờ)", "total": "Tổng (giờ)",
           "sum": "Cộng", "reg": "Regression toàn release", "uat": "Hỗ trợ UAT",
           "grand": "Tổng cộng", "pd": "ngày công", "day": "ngày công", "ass": "Giả định",
           "lv": {1: "low", 2: "medium", 3: "high"},
           "a_min": "- số phút cho mỗi case: thiết kế {design}, review {review}, thực thi {execute}",
           "a_retest": "- dự phòng retest bug: {}% thời gian thực thi",
           "a_size": "- quy mô khi chưa có plan (stream × case mỗi stream): ",
           "a_basis": "- cơ sở: `cases` = đếm trong cases/*.md, `plan` = số stream trong plan.md, "
                      "`estimate` = quy mô mặc định theo mức rủi ro"},
}


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def level(v, what, key):
    k = v.lower() if isinstance(v, str) else v
    if k not in LEVEL:
        fail(f"{key}: {what} must be 1-3 or low|medium|high, got {v!r}")
    return LEVEL[k]


def risk_name(score):
    return "high" if score >= 6 else "medium" if score >= 3 else "low"


def merge(defaults, given):
    out = dict(defaults)
    for k, v in (given or {}).items():
        out[k] = merge(defaults[k], v) if isinstance(v, dict) and isinstance(defaults.get(k), dict) else v
    return out


def compute(model):
    a = merge(DEFAULTS, model.get("assumptions"))
    m = a["minutes_per_case"]
    rows = []
    for t in model.get("tickets", []):
        key = t.get("key") or fail("every ticket needs a key")
        imp, lik = level(t.get("impact", 2), "impact", key), level(t.get("likelihood", 2), "likelihood", key)
        score, risk = imp * lik, risk_name(imp * lik)
        size = a["default_size"][risk]
        streams = int(t.get("streams") or size["streams"])
        if t.get("cases") is None:
            cases, basis = streams * size["cases_per_stream"], t.get("basis") or "estimate"
        else:
            cases, basis = int(t["cases"]), t.get("basis") or "cases"
        design = cases * m["design"] / 60
        review = cases * m["review"] / 60
        execute = cases * m["execute"] / 60
        retest = execute * a["retest_buffer"]
        rows.append({"key": key, "title": t.get("title", ""), "impact": imp, "likelihood": lik,
                     "score": score, "risk": risk, "streams": streams, "cases": cases,
                     "basis": basis, "design_h": round(design, 1), "review_h": round(review, 1),
                     "execute_h": round(execute, 1), "retest_h": round(retest, 1),
                     "total_h": round(design + review + execute + retest, 1)})
    if not rows:
        fail("no tickets")
    rows.sort(key=lambda r: (-r["score"], r["key"]))
    tickets_h = round(sum(r["total_h"] for r in rows), 1)
    grand = round(tickets_h + a["regression_hours"] + a["uat_hours"], 1)
    return {"release": model.get("release", ""), "assumptions": a, "tickets": rows,
            "totals": {"cases": sum(r["cases"] for r in rows), "tickets_h": tickets_h,
                       "regression_h": a["regression_hours"], "uat_h": a["uat_hours"],
                       "grand_h": grand, "person_days": round(grand / a["hours_per_day"], 1)}}


def to_markdown(res, lang):
    t, a = T[lang], res["assumptions"]
    out = [f"## {t['matrix']}", "", f"| {t['imp']} \\ {t['lik']} | low (1) | medium (2) | high (3) |",
           "|---|---|---|---|"]
    for imp in (3, 2, 1):
        cells = []
        for lik in (1, 2, 3):
            keys = [r["key"] for r in res["tickets"] if r["impact"] == imp and r["likelihood"] == lik]
            cells.append(", ".join(keys) or "—")
        out.append(f"| **{t['lv'][imp]} ({imp})** | " + " | ".join(cells) + " |")
    out += ["", f"## {t['est']}", "",
            f"| {t['key']} | {t['title']} | {t['imp']} | {t['lik']} | {t['score']} | {t['risk']} | "
            f"{t['streams']} | {t['cases']} | {t['basis']} | {t['design']} | {t['review']} | "
            f"{t['exec']} | {t['retest']} | {t['total']} |", "|" + "---|" * 14]
    for r in res["tickets"]:
        out.append(f"| {r['key']} | {r['title']} | {r['impact']} | {r['likelihood']} | {r['score']} | "
                   f"{r['risk']} | {r['streams']} | {r['cases']} | {r['basis']} | {r['design_h']} | "
                   f"{r['review_h']} | {r['execute_h']} | {r['retest_h']} | {r['total_h']} |")
    tot = res["totals"]
    out += [f"| **{t['sum']}** | | | | | | | {tot['cases']} | | | | | | {tot['tickets_h']} |", "",
            f"- {t['reg']}: {tot['regression_h']} h", f"- {t['uat']}: {tot['uat_h']} h",
            f"- **{t['grand']}: {tot['grand_h']} h ≈ {tot['person_days']} {t['pd']}** "
            f"(1 {t['day']} = {a['hours_per_day']} h)", "",
            f"### {t['ass']}", "",
            t["a_min"].format(**a["minutes_per_case"]),
            t["a_retest"].format(int(a["retest_buffer"] * 100)),
            t["a_size"] + ", ".join(
                f"{k} {v['streams']}×{v['cases_per_stream']}" for k, v in a["default_size"].items()),
            t["a_basis"], ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("tickets_json")
    ap.add_argument("out_md")
    ap.add_argument("--json", dest="out_json")
    ap.add_argument("--lang", choices=["vi", "en"], default="vi")
    a = ap.parse_args()
    try:
        model = json.loads(Path(a.tickets_json).read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"not found: {a.tickets_json}")
    except json.JSONDecodeError as e:
        fail(f"invalid JSON: {e}")
    res = compute(model)
    Path(a.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out_md).write_text(to_markdown(res, a.lang), encoding="utf-8")
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    tot = res["totals"]
    print(f"wrote {a.out_md}: {len(res['tickets'])} tickets, {tot['cases']} cases, "
          f"{tot['grand_h']} h ≈ {tot['person_days']} person-days")


if __name__ == "__main__":
    main()
