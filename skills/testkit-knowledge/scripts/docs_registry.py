# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp==1.29.1", "pyyaml==6.0.3"]
# ///
"""Project document registry (qa/knowledge/sources.yml): find, hash, convert and ingest project documents.

    uv run docs_registry.py sync   [--path FILE_OR_DIR ...] [--url URL ...] [--no-convert]
    uv run docs_registry.py list   [--json]
    uv run docs_registry.py ingest [ID ...] [--changed] [--queue-only]
    uv run docs_registry.py prune  --yes          delete graph episodes of removed documents

sync   scans docs.paths from qa/config.yml (plus --path), registers new documents, re-hashes known
       ones (sha256) and marks them current | changed | removed; converts .docx (pandoc) and .pdf
       (testkit-spec-review/scripts/pdf_to_md.py) to qa/knowledge/sources/<id>.md. Markdown and
       text files are used in place. --url registers a Confluence / Figma / other page: fetch it
       with your tools and save it as qa/knowledge/sources/<id>.md, then run sync again (the hash is
       taken from that file). Ends with the list of documents that need (re)ingestion.
ingest sends the converted markdown of the given (default: every changed/new) document to the graph,
       one episode per heading section (keys doc:<id>#<section>), reference_time = the file date.
Supported kinds: docx, pdf, md, txt, openapi (registered, not ingested: project-map covers it),
confluence, figma, other. Legacy .doc: convert to .docx first (docx skill).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kg  # noqa: E402

PDF_TO_MD = Path(__file__).resolve().parent.parent.parent / "testkit-spec-review" / "scripts" / "pdf_to_md.py"
EXT_KIND = {".docx": "docx", ".pdf": "pdf", ".md": "md", ".markdown": "md", ".txt": "txt", ".doc": "doc"}
SKIP_PARTS = {"node_modules", ".venv", "venv", "build", "coverage", "qa"}


def registry_path(kb) -> Path:
    return kb.dir / "sources.yml"


def load(kb) -> list[dict]:
    p = registry_path(kb)
    if not p.is_file():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return list(data.get("sources") or [])


def save(kb, items: list[dict]):
    p = registry_path(kb)
    p.parent.mkdir(parents=True, exist_ok=True)
    head = ("# Document registry, maintained by the testkit-knowledge skill (docs_registry.py).\n"
            "# You may edit `owner` and add URL entries; the script fills the rest.\n")
    p.write_text(head + yaml.safe_dump({"sources": items}, sort_keys=False, allow_unicode=True, width=1000),
                 encoding="utf-8")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def kind_of(p: Path) -> str | None:
    k = EXT_KIND.get(p.suffix.lower())
    if k:
        return k
    if p.suffix.lower() in (".yaml", ".yml", ".json") and re.search(r"(?i)(openapi|swagger)", p.name):
        return "openapi"
    return None


def url_kind(u: str) -> str:
    if re.search(r"atlassian\.net/wiki|/confluence/|/display/|/pages/", u):
        return "confluence"
    if "figma.com" in u:
        return "figma"
    return "other"


def scan_paths(kb, extra) -> list[Path]:
    paths = list((kb.config.get("docs") or {}).get("paths") or []) + list(extra or [])
    found = []
    for raw in paths:
        p = (kb.root / raw).resolve()
        if p.is_file():
            if kind_of(p):
                found.append(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                rel = f.relative_to(kb.root).parts if f.is_relative_to(kb.root) else f.parts
                if f.is_file() and kind_of(f) and not (set(rel[:-1]) & SKIP_PARTS) and not f.name.startswith("~$"):
                    found.append(f)
    out, seen = [], set()
    for f in found:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def doc_id(kb, p: Path) -> str:
    return kg.slug(kb.rel(p).rsplit(".", 1)[0], 80)


def convert(kb, item: dict, src: Path) -> str | None:
    """Convert to qa/knowledge/sources/<id>.md; return the converted path (relative) or None."""
    kind = item["kind"]
    if kind in ("md", "txt"):
        return kb.rel(src)
    out = kb.dir / "sources" / f"{item['id']}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    if kind == "docx":
        if not shutil.which("pandoc"):
            item["convert_error"] = "pandoc not installed"
            return None
        r = subprocess.run(["pandoc", "-s", "--track-changes=all", "-t", "gfm",
                            f"--extract-media={kb.rel(kb.dir / 'sources' / (item['id'] + '-media'))}",
                            str(src), "-o", str(out)], cwd=kb.root, capture_output=True, text=True)
    elif kind == "pdf":
        if not PDF_TO_MD.is_file():
            item["convert_error"] = f"{PDF_TO_MD} not found"
            return None
        uv = shutil.which("uv")
        cmd = [uv, "run", "-q", str(PDF_TO_MD), kb.rel(src), kb.rel(out)] if uv else [sys.executable, str(PDF_TO_MD), kb.rel(src), kb.rel(out)]
        r = subprocess.run(cmd, cwd=kb.root, capture_output=True, text=True)
    else:
        return None
    if r.returncode != 0:
        item["convert_error"] = (r.stderr or r.stdout).strip()[-300:]
        return None
    item.pop("convert_error", None)
    header = f"<!-- converted from {kb.rel(src)} (sha256 {item['sha256'][:12]}) on {dt.date.today()} -->\n\n"
    out.write_text(header + out.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    if r.stderr.strip():
        print(f"  note ({item['id']}): {r.stderr.strip()[:200]}")
    return kb.rel(out)


def needs_ingest(it: dict) -> bool:
    return (it.get("status") in ("current", "changed") and it.get("converted") and it.get("kind") != "openapi"
            and it.get("ingested_sha256") != it.get("sha256"))


def cmd_sync(kb, a):
    items = load(kb)
    by_path = {it.get("path"): it for it in items if it.get("path")}
    by_url = {it.get("url"): it for it in items if it.get("url")}
    today = dt.date.today().isoformat()
    seen = set()
    for p in scan_paths(kb, a.path):
        rel = kb.rel(p)
        seen.add(rel)
        h = sha256(p)
        it = by_path.get(rel)
        if not it:
            it = {"id": doc_id(kb, p), "path": rel, "kind": kind_of(p), "sha256": h, "converted": None, "owner": "",
                  "last_seen": today, "last_ingested": None, "ingested_sha256": None, "graph_episodes": [],
                  "status": "current"}
            items.append(it)
            by_path[rel] = it
            print(f"  new      {rel} ({it['kind']})")
            fresh = True
        else:
            fresh = it.get("sha256") != h or it.get("status") == "removed"
            if fresh:
                print(f"  changed  {rel}")
            it.update({"sha256": h, "last_seen": today, "status": "changed" if fresh and it.get("last_ingested") else "current"})
        it["date"] = dt.date.fromtimestamp(p.stat().st_mtime).isoformat()
        if it["kind"] == "doc":
            it["convert_error"] = "legacy .doc: convert to .docx first (docx skill, soffice.py)"
            continue
        if not a.no_convert and (fresh or not it.get("converted") or not (kb.root / it["converted"]).is_file()):
            it["converted"] = convert(kb, it, p)
            if it.get("convert_error"):
                print(f"  ERROR    {rel}: {it['convert_error']}")
    for u in a.url or []:
        if u not in by_url:
            it = {"id": kg.slug(re.sub(r"^https?://", "", u), 80), "url": u, "kind": url_kind(u), "sha256": None,
                  "converted": None, "owner": "", "last_seen": today, "last_ingested": None, "ingested_sha256": None,
                  "graph_episodes": [], "status": "current"}
            items.append(it)
            by_url[u] = it
            print(f"  new      {u} ({it['kind']}): save its content as {kb.rel(kb.dir / 'sources' / (it['id'] + '.md'))}")
    for it in items:
        if it.get("url"):
            md = kb.dir / "sources" / f"{it['id']}.md"
            if md.is_file():
                h = sha256(md)
                if h != it.get("sha256"):
                    it.update({"sha256": h, "converted": kb.rel(md), "last_seen": today,
                               "status": "changed" if it.get("last_ingested") else "current"})
        elif it.get("path") not in seen and it.get("status") != "removed":
            if (kb.root / it["path"]).is_file():
                continue  # registered by an earlier --path; still exists
            it["status"] = "removed"
            conv = kb.root / (it.get("converted") or "")
            if it.get("converted") and conv.is_file() and conv.parent == kb.dir / "sources":
                conv.unlink()  # keep recall from citing a deleted document (git keeps the history)
                it["converted"] = None
            print(f"  removed  {it['path']}")
    save(kb, items)
    todo = [it for it in items if needs_ingest(it)]
    print(f"registry: {kb.rel(registry_path(kb))} ({len(items)} documents)")
    if todo:
        print("needs ingestion: " + ", ".join(it["id"] for it in todo) + "\n  → uv run docs_registry.py ingest --changed")
    else:
        print("needs ingestion: none")
    gone = [it["id"] for it in items if it.get("status") == "removed" and it.get("graph_episodes")]
    if gone:
        print("removed but still in the graph: " + ", ".join(gone) + "  → docs_registry.py prune --yes")
    pending_urls = [it["id"] for it in items if it.get("url") and not it.get("converted")]
    if pending_urls:
        print("URL entries without content yet: " + ", ".join(pending_urls))
    return 0


def cmd_list(kb, a):
    items = load(kb)
    if a.json:
        print(json.dumps(items, indent=2, ensure_ascii=False, default=str))
        return 0
    for it in items:
        flag = "INGEST" if needs_ingest(it) else ""
        print(f"{it['id']:<40} {it.get('kind', ''):<10} {it.get('status', ''):<8} "
              f"ingested {str(it.get('last_ingested') or '-')[:10]:<10} {flag:<6} {it.get('path') or it.get('url')}"
              + (f"  ERROR: {it['convert_error']}" if it.get("convert_error") else ""))
    if not items:
        print("registry empty: run docs_registry.py sync")
    return 0


def cmd_ingest(kb, a):
    items = load(kb)
    sel = [it for it in items if it["id"] in a.ids] if a.ids else [it for it in items if needs_ingest(it)]
    missing = set(a.ids or []) - {it["id"] for it in sel}
    if missing:
        raise SystemExit(f"error: unknown document id(s): {', '.join(sorted(missing))}")
    if not sel:
        print("nothing to ingest")
        return 0
    rc = 0
    for it in sel:
        if not it.get("converted") or not (kb.root / it["converted"]).is_file():
            print(f"  skip {it['id']}: no converted markdown ({it.get('convert_error') or 'run sync'})")
            continue
        text = (kb.root / it["converted"]).read_text(encoding="utf-8", errors="replace")
        where = it.get("path") or it.get("url")
        eps, notes = kg.chunk_episodes(f"doc:{it['id']}", Path(where).name if it.get("path") else it["id"], text,
                                       f"project document {where} ({it['kind']}, sha256 {str(it.get('sha256'))[:12]}); "
                                       f"text: {it['converted']}", it.get("date"), kb.max_chunk, it["converted"])
        for n in sorted(set(notes)):
            print(f"  safety ({it['id']}): {n}")
        print(f"{it['id']}: {len(eps)} section(s)")
        rep = kb.ingest(eps, queue_only=a.queue_only)
        kg.print_report(rep)
        if rep["errors"]:
            rc = 1
            continue
        it["graph_episodes"] = [e["key"] for e in eps]
        if rep["sent"] or rep["skipped"] or rep["queued"]:
            it.update({"last_ingested": dt.datetime.now().replace(microsecond=0).isoformat(),
                       "ingested_sha256": it.get("sha256")})
            if it.get("status") == "changed":
                it["status"] = "current"
    save(kb, items)
    return rc


def cmd_prune(kb, a):
    items = load(kb)
    gone = [it for it in items if it.get("status") == "removed" and it.get("graph_episodes")]
    if not gone:
        print("nothing to prune")
        return 0
    if not a.yes:
        for it in gone:
            print(f"would delete {len(it['graph_episodes'])} episode(s) of {it['id']} ({it.get('path')})")
        print("re-run with --yes to confirm")
        return 2
    st = kb.load_state()
    bucket = kb.state_bucket(st)
    for it in gone:
        for key in it["graph_episodes"]:
            v = bucket.get(key) or {}
            uuid = v.get("uuid") or kb._find_uuid(v.get("name"))
            if uuid:
                kb.call([("delete_episode", {"uuid": uuid, "group_id": kb.group_id})])
            bucket.pop(key, None)
        print(f"pruned {it['id']}")
        it["graph_episodes"] = []
    kb.save_state(st)
    save(kb, items)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", help="project root (default: nearest folder with qa/config.yml)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sync")
    p.add_argument("--path", action="append", help="extra file or folder (repeatable)")
    p.add_argument("--url", action="append", help="register a Confluence/Figma/other URL (repeatable)")
    p.add_argument("--no-convert", action="store_true")
    p = sub.add_parser("list")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("ingest")
    p.add_argument("ids", nargs="*")
    p.add_argument("--changed", action="store_true", help="every new/changed document (default when no ids)")
    p.add_argument("--queue-only", action="store_true")
    p = sub.add_parser("prune")
    p.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.project).resolve() if a.project else kg.find_root(Path.cwd())
    kb = kg.KB(root)
    if not kb.k["enabled"]:
        print("knowledge.enabled is false in qa/config.yml: nothing to do")
        return 0
    try:
        return {"sync": cmd_sync, "list": cmd_list, "ingest": cmd_ingest, "prune": cmd_prune}[a.cmd](kb, a)
    except kg.GraphError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
