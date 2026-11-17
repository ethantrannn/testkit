#!/usr/bin/env python3
"""Turn metrics.json (from metrics.py) into the report files' models.

    python3 build_models.py qa/reports/<NAME>/metrics.json --name "Sprint 46" [--lang en|vi] [--findings findings.json]

Writes next to metrics.json:
  quality-report.md   markdown report (the source of truth people read in the repo)
  report-docx.json    model for testkit-export/scripts/build_docx_report.py
  deck.json           model for testkit-metrics/scripts/build_pptx_deck.py
  workbook.json       model for testkit-export/scripts/build_xlsx.py (optional Excel)

--findings: optional JSON {"summary": "...", "findings": ["..."], "next_steps": ["..."]} written by you
after reading the numbers; without it the summary is generated and findings/next steps are left out.
Labels exist for en and vi; IDs, statuses and severities stay in English. Stdlib only.
"""
import argparse
import json
import sys
from pathlib import Path

L = {
    "en": {
        "title": "Quality report", "period": "Period", "runs": "Runs", "generated": "Generated", "all": "all runs",
        "summary": "Summary", "kpi": "Key figures", "metric": "Metric", "value": "Value",
        "pass_rate": "Pass rate", "executed": "Executed", "planned": "Planned", "ac_cov": "AC coverage",
        "ac_pass": "ACs fully passed", "open_bugs": "Open bugs", "reopen": "Reopen rate", "mttf": "Mean days to fix",
        "mttv": "Mean days to verify", "auto": "Automated (of eligible)", "auto_short": "Automated", "of_eligible": "of eligible", "blocked": "Blocked cases",
        "exec_by_run": "Execution by run", "run": "Run", "title_c": "Title", "date": "Date", "verdict": "Verdict",
        "ac_section": "Acceptance criteria coverage", "ac": "AC", "cases": "Cases", "status": "Status",
        "defects": "Defects", "by_sev": "By severity", "severity": "Severity", "count": "Count",
        "by_status": "By status", "by_comp": "By component", "component": "Component", "density": "Defect density per ticket",
        "ticket": "Ticket", "bugs": "Bugs", "per10": "Bugs / 10 cases", "perac": "Bugs / AC",
        "times": "Fix and verify times", "aging": "Open bug aging", "age": "Age", "age_days": "Age (days)",
        "open_list": "Open bugs", "id": "ID", "automation": "Automation", "auto_none": "No qa/automation/coverage.md yet.",
        "automated": "Automated", "manual_only": "Manual only", "pending": "Pending", "not_eligible": "Not eligible",
        "risky": "Top risky areas", "area": "Area", "score": "Score", "why": "Why",
        "findings": "Findings", "next": "Next steps", "notes": "Data notes", "samples": "samples",
        "results_per_run": "Results per run", "days": "days", "none": "none",
        "auto_summary": "{runs} run(s), {executed} of {planned} cases executed, pass rate {pass_rate}. "
                        "{open} open bug(s) ({sev}); reopen rate {reopen}.",
        "risk_summary": " Highest risk: {area}.",
        "rate_of": "{n} of {d}",
    },
    "vi": {
        "title": "Báo cáo chất lượng", "period": "Giai đoạn", "runs": "Lượt test", "generated": "Ngày lập", "all": "tất cả",
        "summary": "Tổng quan", "kpi": "Chỉ số chính", "metric": "Chỉ số", "value": "Giá trị",
        "pass_rate": "Tỉ lệ đạt", "executed": "Đã chạy", "planned": "Kế hoạch", "ac_cov": "Độ phủ AC",
        "ac_pass": "AC đạt hoàn toàn", "open_bugs": "Bug đang mở", "reopen": "Tỉ lệ mở lại", "mttf": "Thời gian sửa TB (ngày)",
        "mttv": "Thời gian verify TB (ngày)", "auto": "Đã tự động hoá (trên số đủ điều kiện)", "auto_short": "Tự động hoá", "of_eligible": "case đủ điều kiện", "blocked": "Case bị chặn",
        "exec_by_run": "Kết quả theo lượt test", "run": "Lượt", "title_c": "Tiêu đề", "date": "Ngày", "verdict": "Kết luận",
        "ac_section": "Độ phủ tiêu chí chấp nhận", "ac": "AC", "cases": "Test case", "status": "Trạng thái",
        "defects": "Lỗi", "by_sev": "Theo mức độ", "severity": "Mức độ", "count": "Số lượng",
        "by_status": "Theo trạng thái", "by_comp": "Theo thành phần", "component": "Thành phần", "density": "Mật độ lỗi theo ticket",
        "ticket": "Ticket", "bugs": "Bug", "per10": "Bug / 10 case", "perac": "Bug / AC",
        "times": "Thời gian sửa và verify", "aging": "Tuổi bug đang mở", "age": "Tuổi", "age_days": "Tuổi (ngày)",
        "open_list": "Bug đang mở", "id": "ID", "automation": "Tự động hoá", "auto_none": "Chưa có qa/automation/coverage.md.",
        "automated": "Đã tự động", "manual_only": "Chỉ test tay", "pending": "Chờ làm", "not_eligible": "Không đủ điều kiện",
        "risky": "Khu vực rủi ro cao", "area": "Khu vực", "score": "Điểm", "why": "Lý do",
        "findings": "Nhận định", "next": "Việc tiếp theo", "notes": "Ghi chú dữ liệu", "samples": "mẫu",
        "results_per_run": "Kết quả theo lượt test", "days": "ngày", "none": "không có",
        "auto_summary": "{runs} lượt test, đã chạy {executed}/{planned} case, tỉ lệ đạt {pass_rate}. "
                        "{open} bug đang mở ({sev}); tỉ lệ mở lại {reopen}.",
        "risk_summary": " Rủi ro cao nhất: {area}.",
        "rate_of": "{n}/{d}",
    },
}
SEVERITIES = ("blocker", "critical", "major", "minor", "trivial")


def p(v):
    return "—" if v is None else f"{v:g}%"


def n(v):
    return "—" if v is None else f"{v:g}"


def md_table(cols, rows):
    esc = lambda c: str(c).replace("|", "\\|").replace("\n", "<br>")
    return "\n".join(["| " + " | ".join(map(esc, cols)) + " |", "|" + "---|" * len(cols)] +
                     ["| " + " | ".join(map(esc, r)) + " |" for r in rows]) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("metrics")
    ap.add_argument("--name", required=True, help='report name shown in titles, e.g. "Sprint 46" or "Release 2.3"')
    ap.add_argument("--lang", default="en", choices=sorted(L))
    ap.add_argument("--findings", help="JSON with summary / findings / next_steps")
    a = ap.parse_args()
    mpath = Path(a.metrics)
    if not mpath.exists():
        sys.exit(f"build_models: {mpath} not found")
    m = json.loads(mpath.read_text(encoding="utf-8"))
    t = L[a.lang]
    extra = json.loads(Path(a.findings).read_text(encoding="utf-8")) if a.findings else {}
    out_dir = mpath.parent

    T, ac, d, au = m["totals"], m["ac_coverage"], m["defects"], m["automation"]
    sel = m["selection"]
    period = f"{sel['from'] or '…'} → {sel['to'] or '…'}" if sel["mode"] == "date range" else t["all"] if sel["mode"] == "all" else ", ".join(sel["runs"])
    open_n = len(d["open"])
    open_sev = {}
    for b in d["open"]:
        open_sev[b["severity"]] = open_sev.get(b["severity"], 0) + 1
    sev_txt = ", ".join(f"{open_sev[s]} {s}" for s in SEVERITIES if open_sev.get(s)) or t["none"]
    summary = extra.get("summary") or (
        t["auto_summary"].format(runs=T["runs"], executed=T["executed"], planned=T["planned"], pass_rate=p(T["pass_rate"]),
                                 open=open_n, sev=sev_txt, reopen=p(d["reopen_rate"]))
        + (t["risk_summary"].format(area=m["risky_areas"][0]["area"]) if m["risky_areas"] else ""))
    title = f"{t['title']} — {a.name}"
    meta = [[t["period"], period], [t["runs"], ", ".join(sel["runs"])], [t["generated"], m["today"]]]

    kpi_rows = [
        [t["pass_rate"], p(T["pass_rate"])],
        [t["executed"], t["rate_of"].format(n=T["executed"], d=T["planned"])],
        [t["blocked"], str(T["blocked"])],
        [t["ac_cov"], f"{p(ac['coverage_rate'])} ({t['rate_of'].format(n=ac['covered'], d=ac['total'])})"],
        [t["ac_pass"], t["rate_of"].format(n=ac["passed"], d=ac["total"])],
        [t["open_bugs"], f"{open_n} ({sev_txt})"],
        [t["reopen"], p(d["reopen_rate"])],
        [t["mttf"], f"{n(d['mean_days_to_fix'])} ({d['fix_samples']} {t['samples']})"],
        [t["mttv"], f"{n(d['mean_days_to_verify'])} ({d['verify_samples']} {t['samples']})"],
    ]
    if au.get("present"):
        kpi_rows.append([t["auto"], p(au["automated_rate"])])
    run_cols = [t["run"], t["title_c"], t["date"], t["verdict"], t["planned"], t["executed"], "PASS", "FAIL", "BLOCKED", "SKIPPED", t["pass_rate"]]
    run_rows = [[r["id"], r["title"], r["date"] or "—", r["verdict"] or "—", r["planned"], r["executed"], r["pass"], r["fail"],
                 r["blocked"], r["skipped"], p(r["pass_rate"])] for r in m["runs"]]
    ac_rows = [[r["id"], f"{x['id']}: {x['text']}", ", ".join(x["cases"]) or "—", x["status"]] for r in m["runs"] for x in r["acs"]]
    sev_rows = [[s, d["by_severity"][s]] for s in SEVERITIES]
    status_rows = [[k, v] for k, v in d["by_status"].items()]
    comp_rows = [[k, v] for k, v in d["by_component"].items()]
    dens_rows = [[x["ticket"], x["bugs"], x["executed"], n(x["bugs_per_10_cases"]), n(x["bugs_per_ac"])] for x in d["density"]]
    time_rows = [[t["mttf"], f"{n(d['mean_days_to_fix'])} ({d['fix_samples']} {t['samples']})"],
                 [t["mttv"], f"{n(d['mean_days_to_verify'])} ({d['verify_samples']} {t['samples']})"],
                 [t["reopen"], f"{p(d['reopen_rate'])} ({', '.join(d['reopened_bugs']) or t['none']})"]]
    aging_rows = [[k, v] for k, v in d["open_aging"].items()]
    open_rows = [[b["id"], b["title"], b["severity"], b["status"], b["age_days"] if b["age_days"] is not None else "—"] for b in d["open"]]
    risk_rows = [[r["area"], r["score"], "; ".join(r["reasons"])] for r in m["risky_areas"]]
    auto_rows = [[t["automated"], au.get("automated", 0)], [t["manual_only"], au.get("manual_only", 0)],
                 [t["pending"], au.get("pending", 0)], [t["not_eligible"], au.get("not_eligible", 0)]] if au.get("present") else []

    # ---------- markdown
    md = [f"# {title}", ""] + [f"- {k}: {v}" for k, v in meta] + ["", f"## 1. {t['summary']}", "", summary, "",
                                                                    md_table([t["metric"], t["value"]], kpi_rows)]
    if extra.get("findings"):
        md += [f"### {t['findings']}", ""] + [f"- {x}" for x in extra["findings"]] + [""]
    if extra.get("next_steps"):
        md += [f"### {t['next']}", ""] + [f"- {x}" for x in extra["next_steps"]] + [""]
    md += [f"## 2. {t['exec_by_run']}", "", md_table(run_cols, run_rows),
           f"## 3. {t['ac_section']}", "", md_table([t["run"], t["ac"], t["cases"], t["status"]], ac_rows),
           f"## 4. {t['defects']}", "", f"### {t['by_sev']}", "", md_table([t["severity"], t["count"]], sev_rows),
           f"### {t['by_status']}", "", md_table([t["status"], t["count"]], status_rows),
           f"### {t['by_comp']}", "", md_table([t["component"], t["count"]], comp_rows),
           f"### {t['density']}", "", md_table([t["ticket"], t["bugs"], t["executed"], t["per10"], t["perac"]], dens_rows),
           f"### {t['times']}", "", md_table([t["metric"], t["value"]], time_rows),
           f"### {t['aging']}", "", md_table([t["age"], t["count"]], aging_rows),
           f"### {t['open_list']}", "", md_table([t["id"], t["title_c"], t["severity"], t["status"], t["age_days"]], open_rows) if open_rows else t["none"] + "\n",
           f"## 5. {t['automation']}", "", md_table([t["status"], t["count"]], auto_rows) if auto_rows else t["auto_none"] + "\n",
           f"## 6. {t['risky']}", "", md_table([t["area"], t["score"], t["why"]], risk_rows) if risk_rows else t["none"] + "\n"]
    if m.get("warnings"):
        md += [f"## 7. {t['notes']}", ""] + [f"- {w}" for w in m["warnings"]] + [""]
    (out_dir / "quality-report.md").write_text("\n".join(md), encoding="utf-8")

    # ---------- docx model (build_docx_report.py)
    S = lambda rows: [[str(c) for c in r] for r in rows]
    sec = lambda h, blocks, lvl=1: {"heading": h, "level": lvl, "blocks": blocks}
    tbl = lambda cols, rows, widths=None: {"type": "table", "columns": cols, "rows": S(rows), **({"widths": widths} if widths else {})}
    docx = {"title": title, "meta": meta, "landscape": True, "sections": [
        sec(f"1. {t['summary']}", [{"type": "paragraph", "text": summary}, tbl([t["metric"], t["value"]], kpi_rows, [2, 3])]
            + ([{"type": "paragraph", "text": t["findings"], "bold": True}, {"type": "bullets", "items": extra["findings"]}] if extra.get("findings") else [])
            + ([{"type": "paragraph", "text": t["next"], "bold": True}, {"type": "bullets", "items": extra["next_steps"]}] if extra.get("next_steps") else [])),
        sec(f"2. {t['exec_by_run']}", [tbl(run_cols, run_rows, [2, 4, 2, 3, 1.2, 1.2, 1.2, 1.2, 1.5, 1.5, 1.4])]),
        sec(f"3. {t['ac_section']}", [tbl([t["run"], t["ac"], t["cases"], t["status"]], ac_rows, [2, 6, 4, 2])]),
        sec(f"4. {t['defects']}", []),
        sec(t["by_sev"], [tbl([t["severity"], t["count"]], sev_rows, [2, 1])], 2),
        sec(t["by_status"], [tbl([t["status"], t["count"]], status_rows, [2, 1])], 2),
        sec(t["by_comp"], [tbl([t["component"], t["count"]], comp_rows, [4, 1])], 2),
        sec(t["density"], [tbl([t["ticket"], t["bugs"], t["executed"], t["per10"], t["perac"]], dens_rows)], 2),
        sec(t["times"], [{"type": "kv", "rows": S(time_rows)}], 2),
        sec(t["aging"], [tbl([t["age"], t["count"]], aging_rows, [2, 1])], 2),
        sec(t["open_list"], [tbl([t["id"], t["title_c"], t["severity"], t["status"], t["age_days"]], open_rows, [4, 7, 2, 2, 1.5])]
            if open_rows else [{"type": "paragraph", "text": t["none"]}], 2),
        sec(f"5. {t['automation']}", [tbl([t["status"], t["count"]], auto_rows, [2, 1])] if auto_rows else [{"type": "paragraph", "text": t["auto_none"]}]),
        sec(f"6. {t['risky']}", [tbl([t["area"], t["score"], t["why"]], risk_rows, [4, 1, 6])] if risk_rows else [{"type": "paragraph", "text": t["none"]}]),
    ] + ([sec(f"7. {t['notes']}", [{"type": "bullets", "items": m["warnings"]}])] if m.get("warnings") else [])}
    (out_dir / "report-docx.json").write_text(json.dumps(docx, indent=1, ensure_ascii=False), encoding="utf-8")

    # ---------- deck model (build_pptx_deck.py)
    tone = lambda good: "good" if good else "bad"
    tiles = [
        {"label": t["pass_rate"], "value": p(T["pass_rate"]), "note": t["rate_of"].format(n=T["pass"], d=T["executed"]),
         "tone": "good" if (T["pass_rate"] or 0) >= 95 else "warn" if (T["pass_rate"] or 0) >= 85 else "bad"},
        {"label": t["ac_cov"], "value": p(ac["coverage_rate"]), "note": t["rate_of"].format(n=ac["covered"], d=ac["total"]),
         "tone": tone((ac["coverage_rate"] or 0) >= 100)},
        {"label": t["open_bugs"], "value": str(open_n), "note": sev_txt,
         "tone": "bad" if open_sev.get("blocker") or open_sev.get("critical") else "warn" if open_n else "good"},
        {"label": t["reopen"], "value": p(d["reopen_rate"]), "note": f"{len(d['reopened_bugs'])} {t['bugs'].lower()}",
         "tone": "good" if not d["reopen_rate"] else "warn" if d["reopen_rate"] < 20 else "bad"},
        {"label": t["mttf"], "value": n(d["mean_days_to_fix"]), "note": f"{d['fix_samples']} {t['samples']}", "tone": "neutral"},
        {"label": t["auto_short"] if au.get("present") else t["mttv"],
         "value": p(au["automated_rate"]) if au.get("present") else n(d["mean_days_to_verify"]),
         "note": t["rate_of"].format(n=au.get("automated", 0), d=au.get("cases", 0) - au.get("not_eligible", 0)) + " " + t["of_eligible"] if au.get("present") else f"{d['verify_samples']} {t['samples']}",
         "tone": "neutral"},
    ]
    slides = [
        {"type": "title", "title": title, "subtitle": f"{period} · {T['runs']} {t['runs'].lower()} · {m['today']}"},
        {"type": "kpis", "title": t["kpi"], "tiles": tiles, "text": summary},
        {"type": "chart", "title": t["results_per_run"], "chart": "stacked_column",
         "categories": [r["id"] for r in m["runs"]],
         "series": [{"name": s, "values": [r[s.lower()] for r in m["runs"]]} for s in ("PASS", "FAIL", "BLOCKED", "SKIPPED")],
         "bullets": [f"{r['id']}: {r['verdict'] or '—'} · {t['pass_rate'].lower()} {p(r['pass_rate'])}" for r in m["runs"]]},
        {"type": "chart", "title": t["by_sev"], "chart": "bar",
         "categories": list(SEVERITIES), "series": [{"name": t["bugs"], "values": [d["by_severity"][s] for s in SEVERITIES]}],
         "bullets": [f"{t['density']}: " + ", ".join(f"{x['ticket']} {n(x['bugs_per_10_cases'])}" for x in d["density"]),
                     f"{t['reopen']}: {p(d['reopen_rate'])}", f"{t['mttf']}: {n(d['mean_days_to_fix'])}",
                     f"{t['mttv']}: {n(d['mean_days_to_verify'])}"]},
        {"type": "chart", "title": t["aging"], "chart": "column", "categories": list(d["open_aging"]),
         "series": [{"name": t["open_bugs"], "values": list(d["open_aging"].values())}],
         "bullets": [f"{b['id']} ({b['severity']}, {b['age_days']} {t['days']})" for b in d["open"][:4]]},
    ]
    if open_rows:
        slides.append({"type": "table", "title": t["open_list"], "columns": [t["id"], t["title_c"], t["severity"], t["status"], t["age_days"]],
                       "rows": S(open_rows), "widths": [3, 5.6, 1.6, 1.6, 1.8]})
    if risk_rows:
        slides.append({"type": "table", "title": t["risky"], "columns": [t["area"], t["score"], t["why"]], "rows": S(risk_rows), "widths": [4, 1.2, 7]})
    if extra.get("findings") or extra.get("next_steps"):
        groups = [g for g in ({"title": t["findings"], "items": extra.get("findings")},
                              {"title": t["next"], "items": extra.get("next_steps")}) if g["items"]]
        slides.append({"type": "bullets", "title": " · ".join(g["title"] for g in groups), "groups": groups})
    (out_dir / "deck.json").write_text(json.dumps({"title": title, "slides": slides}, indent=1, ensure_ascii=False), encoding="utf-8")

    # ---------- workbook model (testkit-export/scripts/build_xlsx.py)
    col = lambda h, w=14, **k: {"header": h, "width": w, **k}
    wb = {"properties": {"title": title, "creator": "testkit"}, "sheets": [
        {"name": t["summary"], "title": title, "meta": meta, "columns": [col(t["metric"], 34), col(t["value"], 40)], "rows": S(kpi_rows)},
        {"name": t["runs"], "columns": [col(c, 30 if i == 1 else 12) for i, c in enumerate(run_cols)], "rows": run_rows},
        {"name": "AC", "columns": [col(t["run"]), col(t["ac"], 50), col(t["cases"], 40), col(t["status"], 16)], "rows": ac_rows},
        {"name": t["open_list"], "columns": [col(t["id"], 24), col(t["title_c"], 50), col(t["severity"], 12, choices="severity"),
                                             col(t["status"], 12, choices="bug_status"), col(t["age_days"], 10)], "rows": open_rows},
        {"name": t["risky"], "columns": [col(t["area"], 34), col(t["score"], 10), col(t["why"], 60)], "rows": risk_rows},
    ]}
    (out_dir / "workbook.json").write_text(json.dumps(wb, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_dir}/quality-report.md, report-docx.json, deck.json, workbook.json")


if __name__ == "__main__":
    main()
