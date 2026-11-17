"""Find a usable Graphiti MCP server. Standard library only (Python >= 3.10).

Shared by kg.py (this skill) and bin/testkit_graph.py (`testkit graph detect`).

    python graphiti_detect.py [--project DIR] [--url URL] [--json]

Order: 1. --url / knowledge.graphiti.url in qa/config.yml (passed in by the caller)
       2. env TESTKIT_GRAPHITI_URL
       3. MCP server entries whose name contains "graphiti" with an http(s) URL in coding-agent configs:
          .mcp.json, ~/.claude.json (user + this project), ~/.codex/config.toml, .codex/config.toml,
          .cursor/mcp.json, ~/.cursor/mcp.json, ~/.gemini/settings.json, .gemini/settings.json,
          .vscode/mcp.json
       4. http://localhost:8000 (the default `testkit graph up` address)
The first candidate whose /health answers wins. Nothing here prints headers or keys.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://localhost:8000/mcp"
ENV_URL = "TESTKIT_GRAPHITI_URL"


def normalize_url(url: str) -> str:
    """Return the MCP endpoint (…/mcp, no trailing slash: Graphiti 1.1.x answers …/mcp/ with a 307
    redirect that plain POST clients do not follow) for a base URL, …/mcp or …/mcp/."""
    url = url.strip()
    if not re.match(r"^https?://", url):
        raise ValueError(f"not an http(s) URL: {url!r}")
    p = urllib.parse.urlsplit(url)
    path = p.path.rstrip("/")
    if not path.endswith("/mcp"):
        path = (path + "/mcp") if path else "/mcp"
    return urllib.parse.urlunsplit((p.scheme, p.netloc, path, "", ""))


def health_url(url: str) -> str:
    p = urllib.parse.urlsplit(normalize_url(url))
    base = p.path[: -len("/mcp")]
    return urllib.parse.urlunsplit((p.scheme, p.netloc, base + "/health", "", ""))


def probe(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    """GET <base>/health. Returns (ok, short detail). Never raises."""
    try:
        h = health_url(url)
    except ValueError as e:
        return False, str(e)
    try:
        with urllib.request.urlopen(urllib.request.Request(h, headers={"Accept": "application/json"}),
                                    timeout=timeout) as r:
            body = r.read(2000).decode("utf-8", "replace")
            if not 200 <= r.status < 300:
                return False, f"HTTP {r.status}"
            # Another service on the same port may also answer /health: require Graphiti's answer
            # ({"status":"healthy","service":"graphiti-mcp"}).
            try:
                data = json.loads(body)
            except ValueError:
                data = {}
            if "graphiti" in body.lower() or (isinstance(data, dict) and data.get("status") == "healthy"):
                return True, f"HTTP {r.status} {body.strip()[:120]}"
            return False, f"HTTP {r.status} but not a Graphiti server: {body.strip()[:80]}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        return False, f"unreachable ({reason})"


# ---------- coding-agent configs ----------
def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _servers_from_json(data, keys=("mcpServers", "servers")):
    out = []
    if not isinstance(data, dict):
        return out
    for k in keys:
        servers = data.get(k)
        if isinstance(servers, dict):
            for name, spec in servers.items():
                if isinstance(spec, dict):
                    url = spec.get("url") or spec.get("httpUrl") or spec.get("serverUrl")
                    out.append((str(name), url))
    return out


def _servers_from_toml(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        import tomllib  # Python 3.11+
        data = tomllib.loads(text)
        servers = data.get("mcp_servers") or {}
        return [(str(n), s.get("url")) for n, s in servers.items() if isinstance(s, dict)]
    except ImportError:
        pass
    except Exception:
        return []
    # Python 3.10 fallback: [mcp_servers.<name>] sections with url = "..."
    out, name = [], None
    for line in text.splitlines():
        m = re.match(r'^\s*\[\s*mcp_servers\.("?)([^"\]]+)\1\s*\]', line)
        if m:
            name = m.group(2)
            continue
        if line.strip().startswith("["):
            name = None
            continue
        m = re.match(r'^\s*url\s*=\s*"([^"]+)"', line)
        if name and m:
            out.append((name, m.group(1)))
    return out


def agent_candidates(project: Path | None, home: Path | None = None):
    """(source label, server name, url) for every MCP entry named like *graphiti* with an http URL."""
    home = home or Path.home()
    found = []

    def add(label, entries):
        for name, url in entries:
            if "graphiti" in name.lower() and isinstance(url, str) and re.match(r"^https?://", url):
                found.append((label, name, url))

    if project:
        add(".mcp.json (claude, project)", _servers_from_json(_read_json(project / ".mcp.json")))
    cj = _read_json(home / ".claude.json")
    if isinstance(cj, dict):
        if project:
            proj = (cj.get("projects") or {}).get(str(project.resolve()))
            add("~/.claude.json (claude, local)", _servers_from_json(proj))
        add("~/.claude.json (claude, user)", _servers_from_json(cj))
    if project:
        add(".codex/config.toml (codex)", _servers_from_toml(project / ".codex" / "config.toml"))
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    add("~/.codex/config.toml (codex)", _servers_from_toml(codex_home / "config.toml"))
    if project:
        add(".cursor/mcp.json (cursor)", _servers_from_json(_read_json(project / ".cursor" / "mcp.json")))
    add("~/.cursor/mcp.json (cursor)", _servers_from_json(_read_json(home / ".cursor" / "mcp.json")))
    if project:
        add(".gemini/settings.json (gemini)", _servers_from_json(_read_json(project / ".gemini" / "settings.json")))
    add("~/.gemini/settings.json (gemini)", _servers_from_json(_read_json(home / ".gemini" / "settings.json")))
    if project:
        add(".vscode/mcp.json (copilot)", _servers_from_json(_read_json(project / ".vscode" / "mcp.json")))
    return found


def detect(project: Path | None = None, config_url: str | None = None, timeout: float = 2.0,
           probe_default: bool = True) -> dict:
    """Return {"url": mcp url or None, "source": label, "candidates": [{source, url, ok, detail}]}."""
    cands = []
    if config_url:
        cands.append(("qa/config.yml knowledge.graphiti.url", config_url))
    if os.environ.get(ENV_URL):
        cands.append((f"env {ENV_URL}", os.environ[ENV_URL]))
    for label, name, url in agent_candidates(project):
        cands.append((f"{label} server '{name}'", url))
    if probe_default:
        cands.append(("default localhost probe", DEFAULT_URL))
    result = {"url": None, "source": None, "candidates": []}
    seen = set()
    for label, url in cands:
        try:
            norm = normalize_url(url)
        except ValueError as e:
            result["candidates"].append({"source": label, "url": url, "ok": False, "detail": str(e)})
            continue
        if norm in seen:
            continue
        seen.add(norm)
        ok, detail = probe(norm, timeout)
        result["candidates"].append({"source": label, "url": norm, "ok": ok, "detail": detail})
        if ok and not result["url"]:
            result["url"], result["source"] = norm, label
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find a reachable Graphiti MCP server.")
    ap.add_argument("--project", default=".", help="project root (default: current dir)")
    ap.add_argument("--url", help="explicit URL to try first")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = detect(Path(a.project), a.url)
    if a.json:
        print(json.dumps(r, indent=2))
    else:
        for c in r["candidates"]:
            print(f"  {'ok ' if c['ok'] else '-- '} {c['url']}  [{c['source']}] {c['detail']}")
        print(r["url"] or "none")
    return 0 if r["url"] else 1


if __name__ == "__main__":
    sys.exit(main())
