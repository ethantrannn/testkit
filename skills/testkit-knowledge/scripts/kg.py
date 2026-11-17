# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp==1.29.1", "pyyaml==6.0.3"]
# ///
"""testkit knowledge graph client: the only way testkit skills talk to Graphiti (HTTP MCP).

    uv run kg.py detect   [--json]
    uv run kg.py status   [--json]
    uv run kg.py add      --name TITLE --source-description TEXT [--key KEY] [--reference-time ISO]
                          [--file PATH | --text TEXT] [--json-body] [--chunk] [--no-mask] [--queue-only]
    uv run kg.py fact     --subject S --predicate P --object O --fact "sentence (D-… id)"
    uv run kg.py flush    [--retry-failed]
    uv run kg.py search   "question" [--max 10] [--no-files] [--json]
    uv run kg.py episodes [--max 50] [--json]
    uv run kg.py forget   <episode uuid | key> --yes

Run from the project root (or pass --project). Settings come from the `knowledge:` block of
qa/config.yml; the graph group is knowledge.group_id (default: slug of the project folder name).

Where the graph is: knowledge.graphiti.url, env TESTKIT_GRAPHITI_URL, MCP entries named *graphiti*
in coding-agent configs (.mcp.json, ~/.claude.json, ~/.codex/config.toml, .cursor/mcp.json,
~/.gemini/settings.json, .vscode/mcp.json), then http://localhost:8000 (`testkit graph up`).

`add` reads the episode body from --file, --text or stdin. Every episode has a stable KEY
(default: slug of the name); re-adding a key with changed content replaces the old episode,
unchanged content is skipped. Before sending, e-mail addresses and phone numbers are masked
(unless --no-mask) and anything that looks like a secret is replaced by <redacted>.
--chunk splits a markdown body by headings (size limit knowledge.ingest.max_chunk_chars)
into one episode per section with keys KEY#<section>.
If the graph is unreachable, consent is missing, or --queue-only is given, the episode is
queued in qa/knowledge/.pending/ and sent by `flush`.

Graphiti processes episodes in the background with its LLM; `status`/`episodes` check which
sent episodes were stored (and which failed). Exit codes: 0 ok (also: queued, disabled),
1 error, 2 usage, 3 graph unreachable (status/search --graph-only).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import graphiti_detect as gd  # noqa: E402

DEFAULTS = {
    "enabled": True,
    "dir": "qa/knowledge",
    "group_id": "",
    "graphiti": {"enabled": True, "url": "", "timeout_s": 30, "consent": "ask"},
    "ingest": {"max_chunk_chars": 6000, "runs": True, "bugs": True},
}
FAIL_AFTER_S = int(os.environ.get("TESTKIT_KG_FAIL_AFTER_S") or 900)  # sent but not stored after this → failed


class GraphError(Exception):
    pass


# ---------- config ----------
def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "qa" / "config.yml").is_file():
            return p
    return start


def merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = merge(base[k], v) if isinstance(base.get(k), dict) and isinstance(v, dict) else v
    return out


def slug(s: str, maxlen=60) -> str:
    s = unicodedata.normalize("NFKD", s.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:maxlen].strip("-") or "x"


class KB:
    """Project knowledge settings + graph state. Shared by kg.py, decisions.py, docs_registry.py."""

    def __init__(self, root: Path):
        import yaml
        self.root = root
        cfg_path = root / "qa" / "config.yml"
        raw = {}
        if cfg_path.is_file():
            try:
                raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as e:
                raise SystemExit(f"error: cannot parse {cfg_path}: {e}")
        self.has_config = cfg_path.is_file()
        self.config = raw
        k = raw.get("knowledge")
        self.k = merge(DEFAULTS, k if isinstance(k, dict) else {})
        self.dir = root / self.k["dir"]
        gid = self.k.get("group_id") or slug(root.name, 50)
        self.group_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(gid))
        g = self.k["graphiti"]
        self.graph_enabled = bool(self.k["enabled"]) and bool(g.get("enabled", True))
        self.timeout = float(g.get("timeout_s") or 30)
        self.consent = str(g.get("consent") or "ask")
        self.max_chunk = int(self.k["ingest"].get("max_chunk_chars") or 6000)
        self._url = None
        self._detected = None

    # --- locations
    @property
    def pending_dir(self) -> Path:
        return self.dir / ".pending"

    @property
    def state_path(self) -> Path:
        return self.dir / ".graph-state.json"

    def rel(self, p: Path) -> str:
        try:
            return p.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(p)

    # --- graph discovery
    def detect(self, force=False):
        if self._detected is None or force:
            self._detected = gd.detect(self.root, self.k["graphiti"].get("url") or None, timeout=2.5)
            self._url = self._detected["url"]
        return self._detected

    @property
    def url(self):
        if self._detected is None:
            self.detect()
        return self._url

    def local_llm(self) -> bool:
        """True when the graph is the local `testkit graph up` stack configured with a local LLM (Ollama)."""
        home = Path(os.environ.get("TESTKIT_HOME") or Path.home() / ".testkit") / "graphiti" / "testkit-graph.json"
        try:
            meta = json.loads(home.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return bool(meta.get("local_llm")) and self.url and gd.normalize_url(meta.get("url", "")) == self.url

    def consent_ok(self) -> bool:
        return self.consent == "granted" or self.local_llm()

    # --- state (machine-local, git-ignored): which keys were sent to which graph
    def load_state(self) -> dict:
        try:
            st = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        return st

    def save_state(self, st: dict):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(st, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    def state_bucket(self, st: dict) -> dict:
        return st.setdefault(f"{self.url or 'none'}#{self.group_id}", {})

    # --- graph calls
    def call(self, calls: list[tuple[str, dict]]) -> list[dict]:
        if not self.url:
            raise GraphError("no reachable Graphiti (run: testkit graph status)")
        return asyncio.run(_calls(self.url, calls, self.timeout))

    # --- episodes
    def queue(self, ep: dict, reason: str) -> Path:
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        for old in self.pending_dir.glob("*.json"):
            try:
                if json.loads(old.read_text(encoding="utf-8")).get("key") == ep["key"]:
                    old.unlink()
            except (OSError, ValueError):
                pass
        ts = dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
        p = self.pending_dir / f"{ts}-{slug(ep['key'], 50)}.json"
        p.write_text(json.dumps({**ep, "queued_reason": reason}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return p

    def ingest(self, episodes: list[dict], queue_only=False) -> dict:
        """Send episodes (replace changed, skip unchanged) or queue them. Returns counts + messages."""
        rep = {"sent": 0, "skipped": 0, "queued": 0, "errors": 0, "messages": []}
        if not self.k["enabled"]:
            rep["messages"].append("knowledge.enabled is false: nothing ingested")
            return rep
        if not self.graph_enabled:
            rep["messages"].append("knowledge.graphiti.enabled is false: files only, nothing sent")
            return rep
        if self.consent == "denied":
            rep["messages"].append("knowledge.graphiti.consent is denied: files only, nothing sent or queued")
            return rep
        reason = None
        if queue_only:
            reason = "queue-only"
        elif not self.url:
            reason = "graph unreachable"
        elif not self.consent_ok():
            reason = "consent"
        if reason:
            for ep in episodes:
                self.queue(ep, reason)
                rep["queued"] += 1
            if reason == "consent":
                rep["messages"].append(
                    "QUEUED, NOT SENT: the graph's LLM provider receives this content. Ask the user once; if they agree, "
                    "set knowledge.graphiti.consent: granted in qa/config.yml and run: kg.py flush")
            else:
                rep["messages"].append(f"queued {rep['queued']} episode(s) in {self.rel(self.pending_dir)} ({reason}); "
                                       "send later with: kg.py flush")
            return rep
        st = self.load_state()
        bucket = self.state_bucket(st)
        try:
            for ep in episodes:
                try:
                    r = self._send(ep, bucket)
                except GraphError as e:
                    if "unreachable" in str(e) or "connect" in str(e).lower():
                        raise
                    rep["errors"] += 1
                    rep["messages"].append(f"{ep['key']}: {e}")
                    continue
                rep[r] += 1
        except GraphError as e:
            done = {k for k in bucket}
            for ep in episodes:
                if ep["key"] not in done or bucket[ep["key"]].get("sha") != ep["sha"]:
                    self.queue(ep, "graph unreachable")
                    rep["queued"] += 1
            rep["messages"].append(f"graph error ({e}); queued {rep['queued']} episode(s)")
        finally:
            self.save_state(st)
        return rep

    def _send(self, ep: dict, bucket: dict) -> str:
        old = bucket.get(ep["key"])
        if old and old.get("sha") == ep["sha"] and old.get("status") in ("sent", "stored"):
            return "skipped"
        if old:
            uuid = old.get("uuid") or self._find_uuid(old.get("name"))
            if uuid:
                self.call([("delete_episode", {"uuid": uuid, "group_id": self.group_id})])
        args = {"name": ep["name"], "episode_body": ep["body"], "group_id": self.group_id,
                "source": ep.get("source", "text"), "source_description": ep["source_description"]}
        if ep.get("reference_time"):
            args["reference_time"] = ep["reference_time"]
        (res,) = self.call([("add_memory", args)])
        if res.get("error"):
            raise GraphError(res["error"])
        bucket[ep["key"]] = {"name": ep["name"], "sha": ep["sha"], "status": "sent", "uuid": None,
                             "sent_at": now_iso(), "source_description": ep["source_description"],
                             "file": ep.get("file"), "episode": ep}  # body kept until stored, for retries
        return "sent"

    def _find_uuid(self, name):
        if not name:
            return None
        for e in self.episodes(500):
            if e.get("name") == name:
                return e.get("uuid")
        return None

    def episodes(self, n=50) -> list[dict]:
        (res,) = self.call([("get_episodes", {"group_ids": [self.group_id], "max_episodes": n})])
        if res.get("error"):
            raise GraphError(res["error"])
        return res.get("episodes") or []

    def reconcile(self) -> dict:
        """Match sent episodes with stored ones (by name) → stored/failed. Returns status counts."""
        st = self.load_state()
        bucket = self.state_bucket(st)
        eps = {e.get("name"): e for e in self.episodes(1000)}
        now = dt.datetime.now(dt.timezone.utc)
        for key, v in bucket.items():
            e = eps.get(v.get("name"))
            if e:
                v["status"], v["uuid"] = "stored", e.get("uuid")
                v.pop("episode", None)
            elif v.get("status") in ("sent", "stored"):
                sent = parse_time(v.get("sent_at"))
                if v.get("status") == "stored" or (sent and (now - sent).total_seconds() > FAIL_AFTER_S):
                    v["status"] = "failed" if v.get("status") == "sent" else "missing"
        self.save_state(st)
        counts = {}
        for v in bucket.values():
            counts[v.get("status", "?")] = counts.get(v.get("status", "?"), 0) + 1
        return counts

    def flush(self, retry_failed=False) -> dict:
        rep = {"sent": 0, "skipped": 0, "queued": 0, "errors": 0, "messages": []}
        if retry_failed and self.url:
            st = self.load_state()
            n = 0
            for key, v in self.state_bucket(st).items():
                if v.get("status") in ("failed", "missing") and v.get("episode"):
                    v["sha"] = "retry"
                    self.queue(v["episode"], "retry")
                    n += 1
            self.save_state(st)
            rep["messages"].append(f"re-queued {n} failed episode(s)")
        files = sorted(self.pending_dir.glob("*.json")) if self.pending_dir.is_dir() else []
        if not files:
            rep["messages"].append("nothing pending")
            return rep
        if not self.url:
            rep["messages"].append(f"{len(files)} pending; graph unreachable")
            return rep
        if not self.consent_ok():
            rep["messages"].append(f"{len(files)} pending; consent not given (knowledge.graphiti.consent: granted)")
            return rep
        for f in files:
            ep = json.loads(f.read_text(encoding="utf-8"))
            ep.pop("queued_reason", None)
            f.unlink()
            r = self.ingest([ep])
            for k in ("sent", "skipped", "queued", "errors"):
                rep[k] += r[k]
            rep["messages"] += r["messages"]
            if r["queued"]:
                break
        return rep


async def _calls(url: str, calls, timeout: float) -> list[dict]:
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    out = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5), follow_redirects=True) as hc:
            async with streamable_http_client(url, http_client=hc) as (r, w, _):
                async with ClientSession(r, w) as s:
                    await asyncio.wait_for(s.initialize(), timeout)
                    for name, args in calls:
                        res = await asyncio.wait_for(s.call_tool(name, args), timeout)
                        out.append(_result(res))
    except GraphError:
        raise
    except BaseException as e:  # noqa: BLE001 — anyio wraps transport errors in exception groups
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        msg = _first_error(e)
        raise GraphError(f"cannot talk to {url}: {msg}") from None
    return out


def _first_error(e: BaseException) -> str:
    while getattr(e, "exceptions", None):  # (Base)ExceptionGroup from anyio
        e = e.exceptions[0]
    return f"{type(e).__name__}: {e}"[:300]


def _result(res) -> dict:
    data = res.structuredContent
    if not data:
        text = "".join(getattr(c, "text", "") for c in res.content or [])
        try:
            data = json.loads(text)
        except ValueError:
            data = {"error" if res.isError else "message": text}
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    if res.isError and isinstance(data, dict) and "error" not in data:
        data = {"error": json.dumps(data)[:300]}
    return data if isinstance(data, dict) else {"result": data}


# ---------- content safety ----------
SECRET_PATTERNS = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("AWS key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("API key", re.compile(r"\b(?:sk|pk|rk)[-_](?:live|test|proj|ant)?[-_]?[A-Za-z0-9_\-]{16,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("URL credentials", re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)")),
    ("Bearer token", re.compile(r"(?i)(?<=bearer )[A-Za-z0-9._\-]{16,}")),
]
ASSIGN_SECRET = re.compile(r"(?i)\b((?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|"
                           r"client[_-]?secret|private[_-]?key|mật khẩu)\s*[:=]\s*)(['\"]?)([^\s'\"`,;]{6,})\2")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"(?<![\w+])(?:\+?84|0)(?:3|5|7|8|9)\d(?:[ .\-]?\d){7}(?!\w)|"
                   r"(?<![\w])\+\d{1,3}[ .\-]?\(?\d{2,4}\)?[ .\-]?\d{3,4}[ .\-]?\d{3,4}(?!\w)")


def sanitize(text: str, mask_personal=True) -> tuple[str, list[str]]:
    notes = []
    for label, rx in SECRET_PATTERNS:
        text, n = rx.subn("<redacted>", text)
        if n:
            notes.append(f"redacted {n} {label}(s)")
    text, n = ASSIGN_SECRET.subn(lambda m: m.group(1) + m.group(2) + "<redacted>" + m.group(2), text)
    if n:
        notes.append(f"redacted {n} password/secret value(s)")
    if mask_personal:
        text, n = EMAIL.subn("<email>", text)
        if n:
            notes.append(f"masked {n} e-mail address(es)")
        text, n = PHONE.subn("<phone>", text)
        if n:
            notes.append(f"masked {n} phone number(s)")
    return text, notes


# ---------- episodes ----------
def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def parse_time(s):
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def norm_time(s: str | None) -> str:
    if not s:
        return now_iso()
    s = str(s).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s + "T00:00:00Z"
    if not parse_time(s):
        raise SystemExit(f"error: --reference-time {s!r} is not an ISO date/time")
    return s


def make_episode(key, name, body, source_description, reference_time=None, source="text", file=None,
                 mask_personal=True) -> tuple[dict, list[str]]:
    body, notes = sanitize(body, mask_personal)
    title = f"{key}: {name}" if not name.startswith(key) else name
    ep = {"key": key, "name": title[:200], "body": body, "source": source,
          "source_description": source_description[:300], "reference_time": norm_time(reference_time),
          "file": file, "sha": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]}
    return ep, notes


def chunk_markdown(text: str, max_chars: int) -> list[tuple[str, str]]:
    """Split markdown by headings (#, ##, ###) into (heading path, body) chunks of at most max_chars."""
    sections, path, cur, head = [], [], [], None
    for line in text.splitlines():
        m = re.match(r"^(#{1,3})\s+(.+?)\s*#*\s*$", line)
        if m:
            if cur and "".join(cur).strip():
                sections.append((head or "Intro", "\n".join(cur).strip()))
            lvl = len(m.group(1))
            path = path[: lvl - 1] + [m.group(2)]
            head, cur = " > ".join(path), [line]
        else:
            cur.append(line)
    if cur and "".join(cur).strip():
        sections.append((head or "Intro", "\n".join(cur).strip()))
    merged = []
    for h, b in sections:  # merge tiny sections into the previous one
        if merged and len(b) < 200 and len(merged[-1][1]) + len(b) < max_chars:
            merged[-1] = (merged[-1][0], merged[-1][1] + "\n\n" + b)
        else:
            merged.append((h, b))
    out = []
    for h, b in merged:  # split oversize sections by paragraph
        if len(b) <= max_chars:
            out.append((h, b))
            continue
        part, n = "", 1
        for para in re.split(r"\n\s*\n", b):
            while len(para) > max_chars:
                if part:
                    out.append((f"{h} ({n})", part.strip()))
                    n += 1
                    part = ""
                out.append((f"{h} ({n})", para[:max_chars]))
                n += 1
                para = para[max_chars:]
            if len(part) + len(para) + 2 > max_chars and part:
                out.append((f"{h} ({n})", part.strip()))
                n, part = n + 1, ""
            part += para + "\n\n"
        if part.strip():
            out.append((f"{h} ({n})" if n > 1 else h, part.strip()))
    return out


def chunk_episodes(key, name, text, source_description, reference_time, max_chars, file=None, mask_personal=True):
    eps, notes, seen = [], [], {}
    for head, body in chunk_markdown(text, max_chars):
        s = slug(head.split(" > ")[-1], 40)
        seen[s] = seen.get(s, 0) + 1
        k = f"{key}#{s}" + (f"-{seen[s]}" if seen[s] > 1 else "")
        ep, n = make_episode(k, f"{name} — {head}", f"{name} — {head}\n\n{body}", source_description,
                             reference_time, file=file, mask_personal=mask_personal)
        eps.append(ep)
        notes += n
    return eps, notes


# ---------- file search (works without the graph) ----------
def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


STOP = set("the and for with that this what when where which who how are was were has have does did can not from into "
           "about của và cho các những một khi thì là được không có này đó với trong".split())


def file_search(kb: KB, query: str, limit=15) -> list[dict]:
    terms = [t for t in re.findall(r"[\w\-]{3,}", fold(query)) if t not in STOP]
    if not terms or not kb.dir.is_dir():
        return []
    hits = []
    for f in sorted(kb.dir.rglob("*.md")):
        r = kb.rel(f)
        if "/.pending/" in r:
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        tag = ""
        if "/decisions/" in r and lines[:1] == ["---"]:
            st = next((ln.split(":", 1)[1].strip() for ln in lines[:15] if ln.startswith("status:")), "")
            sup = next((ln.split(":", 1)[1].strip() for ln in lines[:15] if ln.startswith("superseded_by:")), "")
            if st and st != "accepted":
                tag = f" [{st.upper()}{' by ' + sup if sup and sup != 'null' else ''}]"
        for i, line in enumerate(lines, 1):
            fl = fold(line)
            score = sum(1 for t in set(terms) if t in fl)
            if score:
                hits.append({"file": r, "line": i,
                             "score": score + (0.5 if "/decisions/" in r and not tag else 0) - (0.5 if tag else 0),
                             "text": line.strip()[:200] + tag})
    hits.sort(key=lambda h: (-h["score"], h["file"], h["line"]))
    return hits[:limit]


def search(kb: KB, query: str, n=10, files=True) -> dict:
    out = {"query": query, "group_id": kb.group_id, "graph": None, "graph_error": None, "facts": [], "nodes": [],
           "files": file_search(kb, query) if files else [], "pending": 0}
    if kb.pending_dir.is_dir():
        out["pending"] = len(list(kb.pending_dir.glob("*.json")))
    if not (kb.k["enabled"] and kb.graph_enabled):
        out["graph_error"] = "graph disabled in qa/config.yml"
        return out
    if not kb.url:
        out["graph_error"] = "graph unreachable"
        return out
    out["graph"] = kb.url
    try:
        facts, nodes = kb.call([
            ("search_memory_facts", {"query": query, "group_ids": [kb.group_id], "max_facts": n}),
            ("search_nodes", {"query": query, "group_ids": [kb.group_id], "max_nodes": n}),
        ])
    except GraphError as e:
        out["graph_error"] = str(e)
        return out
    for r in (facts, nodes):
        if r.get("error"):
            out["graph_error"] = r["error"] + (" (the graph's embedder/LLM API is not reachable or not configured; "
                                               "see: testkit graph logs)" if "Connection error" in r["error"] else "")
    names = {}
    st = kb.state_bucket(kb.load_state())
    for key, v in st.items():
        if v.get("uuid"):
            names[v["uuid"]] = (key, v.get("file"))
    for f in facts.get("facts") or []:
        src = [names.get(u, (u[:8], None)) for u in f.get("episodes") or []]
        out["facts"].append({"fact": f.get("fact"), "name": f.get("name"), "valid_at": f.get("valid_at"),
                             "invalid_at": f.get("invalid_at"), "expired_at": f.get("expired_at"),
                             "sources": [k for k, _ in src], "files": [p for _, p in src if p]})
    for nd in nodes.get("nodes") or []:
        out["nodes"].append({"name": nd.get("name"), "labels": [x for x in nd.get("labels") or [] if x != "Entity"],
                             "summary": (nd.get("summary") or "")[:300]})
    return out


# ---------- CLI ----------
def print_report(rep):
    print(f"sent {rep['sent']}, unchanged {rep['skipped']}, queued {rep['queued']}, errors {rep['errors']}")
    for m in rep["messages"]:
        print("  " + m)


def cmd_detect(kb: KB, a):
    r = kb.detect()
    if a.json:
        print(json.dumps(r, indent=2))
        return 0 if r["url"] else 3
    for c in r["candidates"]:
        print(f"  {'ok' if c['ok'] else '--'} {c['url']}  [{c['source']}] {c['detail']}")
    if not r["url"]:
        print("graph: none reachable (files-only mode). Start one with: testkit graph up")
        return 3
    print(f"graph: {r['url']}  (from {r['source']})")
    try:
        (s,) = kb.call([("get_status", {})])
        print(f"get_status: {s.get('status')} — {s.get('message')}")
        return 0 if s.get("status") == "ok" else 1
    except GraphError as e:
        print(f"get_status: failed — {e}")
        return 1


def cmd_status(kb: KB, a):
    info = {"project": str(kb.root), "config": kb.has_config, "knowledge_enabled": kb.k["enabled"],
            "graph_enabled": kb.graph_enabled, "group_id": kb.group_id, "dir": kb.rel(kb.dir),
            "consent": kb.consent, "url": None, "get_status": None, "pending": 0, "episodes": {}}
    if kb.pending_dir.is_dir():
        info["pending"] = len(list(kb.pending_dir.glob("*.json")))
    files = {}
    for sub, pat in (("decisions", "decisions/D-*.md"), ("sources", "sources/*.md")):
        files[sub] = len(list(kb.dir.glob(pat))) if kb.dir.is_dir() else 0
    files["project_map"] = (kb.dir / "project-map.md").is_file()
    info["files"] = files
    code = 0
    if kb.graph_enabled:
        info["url"] = kb.url
        if kb.url:
            try:
                (s,) = kb.call([("get_status", {})])
                info["get_status"] = f"{s.get('status')}: {s.get('message')}"
                info["episodes"] = kb.reconcile()
                info["local_llm"] = kb.local_llm()
            except GraphError as e:
                info["get_status"] = f"error: {e}"
                code = 1
        else:
            code = 3
    if a.json:
        print(json.dumps(info, indent=2))
        return code
    print(f"project      {info['project']}  (qa/config.yml {'found' if kb.has_config else 'MISSING'})")
    print(f"knowledge    {'enabled' if kb.k['enabled'] else 'DISABLED'}; dir {info['dir']}; group_id {kb.group_id}")
    print(f"files        project-map.md {'yes' if files['project_map'] else 'no'}; decisions {files['decisions']}; "
          f"converted sources {files['sources']}")
    if not kb.graph_enabled:
        print("graph        disabled (knowledge.graphiti.enabled: false) — files only")
        return 0
    print(f"graph        {info['url'] or 'unreachable (files-only; start one: testkit graph up)'}")
    if info["get_status"]:
        print(f"get_status   {info['get_status']}")
    print(f"consent      {kb.consent}{' (local LLM: not needed)' if info.get('local_llm') else ''}")
    print(f"pending      {info['pending']} queued episode(s){' — run: kg.py flush' if info['pending'] else ''}")
    if info["episodes"]:
        print("episodes     " + ", ".join(f"{k} {v}" for k, v in sorted(info["episodes"].items())))
        if info["episodes"].get("failed"):
            print("             failed = sent but never stored (LLM/API error?): see `testkit graph logs`, "
                  "then kg.py flush --retry-failed")
    return code


def read_body(a) -> str:
    if a.text is not None:
        return a.text
    if a.file and a.file != "-":
        p = Path(a.file)
        if not p.is_file():
            raise SystemExit(f"error: file not found: {a.file}")
        return p.read_text(encoding="utf-8", errors="replace")
    if sys.stdin.isatty():
        raise SystemExit("error: give --file, --text or pipe the body on stdin")
    return sys.stdin.read()


def cmd_add(kb: KB, a):
    body = read_body(a)
    if not body.strip():
        raise SystemExit("error: empty episode body")
    key = a.key or slug(a.name)
    file_rel = kb.rel(Path(a.file)) if a.file and a.file != "-" else None
    if a.json_body:
        try:
            json.loads(body)
        except ValueError as e:
            raise SystemExit(f"error: --json-body but the body is not JSON: {e}")
    if a.chunk:
        eps, notes = chunk_episodes(key, a.name, body, a.source_description, a.reference_time, kb.max_chunk,
                                    file_rel, not a.no_mask)
    else:
        if len(body) > kb.max_chunk * 2 and not a.json_body:
            print(f"warning: body is {len(body)} chars; consider --chunk", file=sys.stderr)
        ep, notes = make_episode(key, a.name, body, a.source_description, a.reference_time,
                                 "json" if a.json_body else "text", file_rel, not a.no_mask)
        eps = [ep]
    for n in sorted(set(notes)):
        print(f"  safety: {n}")
    rep = kb.ingest(eps, queue_only=a.queue_only)
    print_report(rep)
    return 1 if rep["errors"] else 0


def cmd_fact(kb: KB, a):
    """add_triplet: one fact written directly (no LLM extraction; needs only the embedder)."""
    if not kb.graph_enabled:
        print("graph disabled in qa/config.yml: nothing sent")
        return 0
    if not kb.url:
        print("graph unreachable: fact not sent (facts are not queued; keep them in the decision/map files)")
        return 3
    if not kb.consent_ok():
        print("consent missing: set knowledge.graphiti.consent: granted after asking the user")
        return 0
    fact, notes = sanitize(a.fact)
    for n in notes:
        print(f"  safety: {n}")
    (res,) = kb.call([("add_triplet", {"source_node_name": a.subject, "edge_name": a.predicate.upper().replace(" ", "_"),
                                       "fact": fact, "target_node_name": a.object, "group_id": kb.group_id})])
    if res.get("error"):
        print(f"error: {res['error']}", file=sys.stderr)
        return 1
    print(res.get("message") or "added")
    return 0


def cmd_flush(kb: KB, a):
    rep = kb.flush(a.retry_failed)
    print_report(rep)
    return 1 if rep["errors"] else 0


def cmd_search(kb: KB, a):
    r = search(kb, a.query, a.max, not a.no_files)
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return 0
    if r["graph_error"]:
        print(f"GRAPH: unavailable — {r['graph_error']}. Results below are from files only.")
    else:
        print(f"GRAPH ({r['graph']}, group {r['group_id']}):")
        if not r["facts"] and not r["nodes"]:
            print("  no matching facts or entities")
        for i, f in enumerate(r["facts"], 1):
            stale = f.get("invalid_at") or f.get("expired_at")
            meta = []
            if f.get("valid_at"):
                meta.append(f"valid from {f['valid_at'][:10]}")
            if stale:
                meta.append(f"NO LONGER VALID since {stale[:10]}")
            meta.append("source: " + ("; ".join(f["sources"]) if f["sources"] else "direct fact (kg.py fact)"))
            print(f"  F{i}. {f['fact']}  [{'; '.join(meta)}]")
        for nd in r["nodes"]:
            lab = f" ({', '.join(nd['labels'])})" if nd["labels"] else ""
            print(f"  - {nd['name']}{lab}" + (f": {nd['summary']}" if nd["summary"] else ""))
    if r["pending"]:
        print(f"NOTE: {r['pending']} episode(s) still pending — the graph may be behind the files.")
    if not a.no_files:
        print(f"FILES ({kb.rel(kb.dir)}):")
        if not r["files"]:
            print("  no matching lines")
        for h in r["files"]:
            print(f"  {h['file']}:{h['line']}: {h['text']}")
    return 0


def cmd_episodes(kb: KB, a):
    try:
        eps = kb.episodes(a.max)
        kb.reconcile()
    except GraphError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps(eps, indent=2, ensure_ascii=False))
        return 0
    if not eps:
        print(f"no episodes in group {kb.group_id}")
    for e in eps:
        print(f"{e.get('uuid')}  {(e.get('created_at') or '')[:19]}  {e.get('name')}  [{e.get('source_description')}]")
    return 0


def cmd_forget(kb: KB, a):
    st = kb.load_state()
    bucket = kb.state_bucket(st)
    uuid, key = a.target, None
    if a.target in bucket:
        key = a.target
        uuid = bucket[key].get("uuid") or kb._find_uuid(bucket[key].get("name"))
    else:
        key = next((k for k, v in bucket.items() if v.get("uuid") == a.target), None)
    if not uuid or not re.fullmatch(r"[0-9a-fA-F\-]{32,36}", uuid):
        print(f"error: no stored episode for {a.target!r} (see: kg.py episodes)", file=sys.stderr)
        return 1
    if not a.yes:
        print(f"would delete episode {uuid}{f' ({key})' if key else ''} and the entities/facts only it created. "
              "Re-run with --yes to confirm.")
        return 2
    (res,) = kb.call([("delete_episode", {"uuid": uuid, "group_id": kb.group_id})])
    if res.get("error"):
        print(f"error: {res['error']}", file=sys.stderr)
        return 1
    if key:
        bucket.pop(key, None)
        kb.save_state(st)
    print(res.get("message") or "deleted")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", help="project root (default: nearest folder with qa/config.yml)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("detect")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("add")
    p.add_argument("--name", required=True, help="episode title")
    p.add_argument("--key", help="stable id (default: slug of --name), e.g. D-20261117-01, map, doc:SRS, run:PROJ-123")
    p.add_argument("--source-description", required=True, help="where it came from + file path")
    p.add_argument("--reference-time", help="ISO date/time the content is valid from (default: now)")
    p.add_argument("--file", help="body file, or - for stdin")
    p.add_argument("--text", help="body text")
    p.add_argument("--json-body", action="store_true", help="body is JSON (Graphiti source=json)")
    p.add_argument("--chunk", action="store_true", help="split markdown by headings into several episodes")
    p.add_argument("--no-mask", action="store_true", help="do not mask e-mails/phones (secrets are always redacted)")
    p.add_argument("--queue-only", action="store_true", help="only queue in .pending/")
    p = sub.add_parser("fact", help="add one fact directly (add_triplet; works without an LLM, needs an embedder)")
    p.add_argument("--subject", required=True)
    p.add_argument("--predicate", required=True, help="e.g. CAN_CANCEL")
    p.add_argument("--object", required=True)
    p.add_argument("--fact", required=True, help="the fact as a sentence; include the decision/source id")
    p = sub.add_parser("flush")
    p.add_argument("--retry-failed", action="store_true", help="also re-send episodes the graph never stored")
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--max", type=int, default=10)
    p.add_argument("--no-files", action="store_true", help="graph only")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("episodes")
    p.add_argument("--max", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("forget")
    p.add_argument("target", help="episode uuid or key")
    p.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.project).resolve() if a.project else find_root(Path.cwd())
    kb = KB(root)
    if not kb.k["enabled"] and a.cmd not in ("status", "detect"):
        print("knowledge.enabled is false in qa/config.yml: nothing to do")
        return 0
    try:
        return {"detect": cmd_detect, "status": cmd_status, "add": cmd_add, "flush": cmd_flush,
                "search": cmd_search, "fact": cmd_fact, "episodes": cmd_episodes, "forget": cmd_forget}[a.cmd](kb, a)
    except GraphError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
