"""Run a local Graphiti knowledge graph for testkit (`testkit graph <cmd>`). Standard library only.

    testkit graph detect  [--project DIR] [--json]       print the reachable Graphiti MCP URL, or "none"
    testkit graph up      [--provider P] [--model M] [--embedder E] [--embedder-model M]
                          [--base-url URL] [--port 8000] [--expose-db] [--force] [--no-wait]
    testkit graph status                                  container, health, get_status, provider
    testkit graph logs    [--tail N]
    testkit graph down                                    stop the container (data is kept)
    testkit graph connect --agents claude,codex,gemini [--url URL] [--name graphiti] [--dry-run]
    testkit graph uninstall [--purge]                     down + remove the folder (--purge: also the graph data)

`up` reuses any Graphiti that is already reachable (qa/config.yml knowledge.graphiti.url,
TESTKIT_GRAPHITI_URL, coding-agent MCP configs, http://localhost:8000). Otherwise it writes
$TESTKIT_HOME/graphiti/ (default ~/.testkit/graphiti/): docker-compose.yml (pinned image
zepai/knowledge-graph-mcp, FalkorDB + MCP server in one container, ports bound to 127.0.0.1),
config.yaml (LLM + embedder) and .env (API keys copied from your environment, mode 600), then
starts it and waits until it is healthy.

Providers (--provider; default: the first whose key is set in the environment):
  openai        OPENAI_API_KEY                 LLM + embedder (+ reranker)
  anthropic     ANTHROPIC_API_KEY              needs an embedder: VOYAGE_API_KEY, OPENAI_API_KEY or GOOGLE_API_KEY
  gemini        GOOGLE_API_KEY                 LLM + embedder (+ reranker)
  groq          GROQ_API_KEY                   needs an embedder like anthropic
  azure_openai  AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT
                (+ AZURE_OPENAI_EMBEDDINGS_ENDPOINT, AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT)
  ollama        none; Ollama on this machine (--base-url, default http://host.docker.internal:11434/v1),
                needs --model and an embedding model (--embedder-model, default nomic-embed-text)
  none          no LLM: the graph runs (status, episodes list) but adding memories and searching fail.
                Only for checking the stack.
Embedders (--embedder): openai | gemini | voyage | azure_openai | ollama. The Graphiti MCP server
(1.1.3) has no sentence_transformers embedder; use ollama for a local one.

Env: TESTKIT_HOME (default ~/.testkit), TESTKIT_GRAPHITI_IMAGE (override the pinned image).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

IMAGE = os.environ.get("TESTKIT_GRAPHITI_IMAGE", "zepai/knowledge-graph-mcp:1.1.3-graphiti-0.31.2")
PROJECT = "testkit-graphiti"  # docker compose project name
KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT / "skills" / "testkit-knowledge" / "scripts"))
try:
    import graphiti_detect as gd  # noqa: E402
except ImportError:  # pragma: no cover
    sys.exit(f"error: {KIT}/skills/testkit-knowledge/scripts/graphiti_detect.py not found; reinstall the kit")

UTF8 = (sys.stdout.encoding or "").lower().startswith("utf")
OK, WARN, FAIL = ("✔", "!", "✘") if UTF8 else ("[ok]", "[!]", "[x]")

KEYS = {  # provider -> env vars it needs (LLM side)
    "openai": ["OPENAI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "gemini": ["GOOGLE_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "azure_openai": ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"],
    "ollama": [],
    "none": [],
}
EMB_KEYS = {
    "openai": ["OPENAI_API_KEY"],
    "gemini": ["GOOGLE_API_KEY"],
    "voyage": ["VOYAGE_API_KEY"],
    "azure_openai": ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_EMBEDDINGS_ENDPOINT", "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT"],
    "ollama": [],
    "none": [],
}
OPTIONAL_ENV = ["OPENAI_API_URL", "OPENAI_ORGANIZATION_ID", "ANTHROPIC_API_URL", "GOOGLE_PROJECT_ID", "GOOGLE_LOCATION",
                "GROQ_API_URL", "VOYAGE_API_URL", "AZURE_OPENAI_API_VERSION", "USE_AZURE_AD"]
EMBEDDER_DEFAULTS = {  # embedder -> (model, dimensions)
    "openai": ("text-embedding-3-small", 1536),
    "gemini": ("models/text-embedding-004", 768),
    "voyage": ("voyage-3", 1024),
    "azure_openai": ("text-embedding-3-small", 1536),
    "ollama": ("nomic-embed-text", 768),
    "none": ("text-embedding-3-small", 1536),
}
OLLAMA_URL = "http://host.docker.internal:11434/v1"
NO_LLM_URL = "http://127.0.0.1:9/v1"  # nothing listens there: LLM/embedder calls fail fast

ENTITY_TYPES = [  # QA-oriented; names without a built-in model become documentation-only types
    ("Requirement", "Specific needs, features, acceptance criteria or business rules that must be fulfilled"),
    ("Procedure", "Standard operating procedures, workflows and sequential instructions"),
    ("Feature", "A product feature, module or capability of the application under test"),
    ("Screen", "A UI screen, page, route or dialog of the application"),
    ("ApiEndpoint", "An HTTP/GraphQL API endpoint or operation, e.g. 'POST /api/orders'"),
    ("Role", "A user role, permission or access level, e.g. admin, member"),
    ("DataEntity", "A business data object and its states, e.g. Order with status PAID"),
    ("Decision", "A recorded product, scope or testing decision (id like D-20261117-01)"),
    ("Bug", "A defect report (id like BUG-001 or a tracker key) and its status"),
    ("TestCase", "A test case or test run (ids like TC-S1-001, run ids)"),
    ("Environment", "A test or deployment environment, e.g. staging, production"),
    ("Integration", "A third-party service or system the product talks to, e.g. payment gateway"),
    ("Document", "A specification, design or other source document"),
    ("Organization", "Companies, teams or formal groups"),
    ("Person", "An individual human referenced in the content (by role, not personal data)"),
    ("Event", "Time-bound activities: releases, meetings, incidents"),
]


def ok(m):
    print(f"  {OK} {m}")


def warn(m):
    print(f"  {WARN} {m}")


def die(m, code=1):
    print(f"  {FAIL} {m}", file=sys.stderr)
    sys.exit(code)


def home_dir() -> Path:
    return Path(os.environ.get("TESTKIT_HOME") or Path.home() / ".testkit") / "graphiti"


def run(cmd, cwd=None, check=True, capture=False, timeout=None):
    try:
        r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture, timeout=timeout)
    except FileNotFoundError:
        die(f"command not found: {cmd[0]}")
    except subprocess.TimeoutExpired:
        die(f"timed out: {' '.join(cmd[:4])}")
    if check and r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()[-800:] if capture else ""
        die(f"failed ({r.returncode}): {' '.join(cmd[:5])}\n{msg}")
    return r


def need_docker():
    if not shutil.which("docker"):
        die("Docker is not installed. Install Docker Desktop (macOS/Windows) or Docker Engine (Linux), then retry.")
    r = run(["docker", "info", "--format", "{{.ServerVersion}}"], check=False, capture=True, timeout=30)
    if r.returncode != 0:
        die("Docker is installed but the daemon is not running. Start Docker Desktop / the docker service.")
    r = run(["docker", "compose", "version", "--short"], check=False, capture=True, timeout=30)
    if r.returncode != 0:
        die("The Docker Compose plugin is missing (`docker compose`). Install docker-compose-plugin.")
    return r.stdout.strip()


def compose(*args, capture=False, check=True, timeout=None):
    d = home_dir()
    if not (d / "docker-compose.yml").is_file():
        die(f"No local Graphiti set up in {d}. Run: testkit graph up")
    return run(["docker", "compose", "-p", PROJECT, "-f", str(d / "docker-compose.yml"), *args],
               cwd=d, capture=capture, check=check, timeout=timeout)


def find_project(start: Path) -> Path | None:
    for p in [start, *start.parents]:
        if (p / "qa" / "config.yml").is_file():
            return p
    return None


def config_url(project: Path | None) -> str | None:
    """knowledge.graphiti.url from qa/config.yml (tiny line scan; no YAML dependency)."""
    if not project:
        return None
    try:
        lines = (project / "qa" / "config.yml").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    stack = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        ind = len(line) - len(line.lstrip())
        m = re.match(r"^\s*([\w-]+)\s*:\s*(.*?)\s*(?:#.*)?$", line)
        if not m:
            continue
        while stack and stack[-1][0] >= ind:
            stack.pop()
        stack.append((ind, m.group(1)))
        if [k for _, k in stack] == ["knowledge", "graphiti", "url"]:
            v = m.group(2).strip("'\"")
            return v or None
    return None


def http_ok(url, timeout=3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def mcp_status(url: str, timeout=20.0) -> tuple[bool, str]:
    """Call the get_status tool with a minimal streamable-HTTP MCP exchange (stdlib only)."""
    hdr = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

    def post(payload, sid=None):
        h = dict(hdr)
        if sid:
            h["Mcp-Session-Id"] = sid
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=h, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            sid = r.headers.get("Mcp-Session-Id") or sid
        if body.lstrip().startswith("{"):
            return json.loads(body), sid
        for line in body.splitlines():  # SSE: take the last data line holding a JSON-RPC result
            if line.startswith("data:") and '"jsonrpc"' in line:
                msg = json.loads(line[5:].strip())
                if "result" in msg or "error" in msg:
                    return msg, sid
        return None, sid

    try:
        init, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "testkit-graph", "version": "1"}}})
        if not init or "result" not in init:
            return False, f"initialize failed: {init}"
        post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
        res, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "get_status", "arguments": {}}}, sid)
        r = (res or {}).get("result") or {}
        data = r.get("structuredContent") or {}
        if not data:
            for c in r.get("content") or []:
                if c.get("type") == "text":
                    try:
                        data = json.loads(c["text"])
                    except ValueError:
                        data = {"message": c["text"]}
        data = data.get("result", data) if isinstance(data, dict) else {}
        return data.get("status") == "ok", data.get("message") or json.dumps(res)[:200]
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


# ---------- detect ----------
def cmd_detect(a):
    project = Path(a.project).resolve() if a.project else find_project(Path.cwd())
    r = gd.detect(project, config_url(project))
    if a.json:
        print(json.dumps(r, indent=2))
    else:
        for c in r["candidates"]:
            print(f"  {OK if c['ok'] else '-'} {c['url']}  ({c['source']}: {c['detail']})", file=sys.stderr)
        print(r["url"] or "none")
    return 0 if r["url"] else 1


# ---------- up ----------
def pick_provider(a):
    env = os.environ
    if a.provider:
        prov = a.provider
    elif env.get("OPENAI_API_KEY"):
        prov = "openai"
    elif env.get("ANTHROPIC_API_KEY"):
        prov = "anthropic"
    elif env.get("GOOGLE_API_KEY"):
        prov = "gemini"
    elif env.get("GROQ_API_KEY"):
        prov = "groq"
    elif env.get("AZURE_OPENAI_API_KEY"):
        prov = "azure_openai"
    elif http_ok("http://127.0.0.1:11434/api/version", 1.5):
        prov = "ollama"
        print("  - no LLM API key found; using the local Ollama")
    else:
        die("No LLM provider available. Set one of these environment variables (in your shell, not in a file you "
            "commit) and re-run:\n      OPENAI_API_KEY  |  ANTHROPIC_API_KEY (+ VOYAGE_API_KEY or OPENAI_API_KEY for "
            "embeddings)  |  GOOGLE_API_KEY  |  GROQ_API_KEY (+ embedder key)  |  AZURE_OPENAI_*\n"
            "    or run Ollama locally and use: testkit graph up --provider ollama --model <model>")
    if a.embedder:
        emb = a.embedder
    elif prov in ("openai", "gemini", "azure_openai", "ollama", "none"):
        emb = prov
    else:  # anthropic / groq have no embeddings
        emb = next((e for e, k in (("voyage", "VOYAGE_API_KEY"), ("openai", "OPENAI_API_KEY"),
                                   ("gemini", "GOOGLE_API_KEY")) if env.get(k)), None)
        if not emb:
            if http_ok("http://127.0.0.1:11434/api/version", 1.5):
                emb = "ollama"
            else:
                die(f"{prov} has no embedding model. Also set VOYAGE_API_KEY, OPENAI_API_KEY or GOOGLE_API_KEY, "
                    "or run Ollama and add: --embedder ollama")
    if emb == "sentence_transformers":
        die("The Graphiti MCP server (1.1.3) has no sentence_transformers embedder. For local embeddings run Ollama "
            "(ollama pull nomic-embed-text) and use --embedder ollama.")
    if emb not in EMB_KEYS:
        die(f"unknown embedder {emb!r} (openai, gemini, voyage, azure_openai, ollama)")
    missing = [k for k in KEYS[prov] + EMB_KEYS[emb] if not env.get(k)]
    if missing:
        die("Missing environment variable(s): " + ", ".join(sorted(set(missing))) +
            "\n    Export them in your shell (never paste keys into chat or commit them), then re-run.")
    if prov in ("anthropic", "groq", "ollama") and not (a.model or env.get("MODEL_NAME")):
        die(f"--model is required for {prov} (the model name your account / Ollama install offers).")
    if prov == "azure_openai" and not (a.model or env.get("MODEL_NAME")):
        a.model = env.get("AZURE_OPENAI_DEPLOYMENT")
    return prov, emb


def yaml_str(v) -> str:
    return json.dumps(str(v))  # JSON strings are valid YAML scalars


def render_config(prov, emb, a) -> str:
    base = a.base_url or OLLAMA_URL
    lines = ["# Written by `testkit graph up`. Secrets come from .env via ${VAR} references.",
             "server:", "  transport: \"http\"", "  host: \"0.0.0.0\"", "  port: 8000", "", "llm:"]
    if prov == "ollama":
        lines += ["  provider: \"openai\"", f"  model: {yaml_str(a.model or '${MODEL_NAME}')}",
                  "  max_tokens: 4096", "  structured_output_mode: \"json_object\"", "  providers:", "    openai:",
                  "      api_key: \"ollama\"", f"      api_url: {yaml_str(base)}"]
    elif prov == "none":
        lines += ["  provider: \"openai\"", "  model: \"none\"", "  providers:", "    openai:",
                  "      api_key: \"not-set\"", f"      api_url: {yaml_str(NO_LLM_URL)}"]
    else:
        model = a.model or "${MODEL_NAME:gpt-6-luna}"
        lines += [f"  provider: {yaml_str(prov)}", f"  model: {yaml_str(model)}", "  max_tokens: 4096", "  providers:"]
        lines += provider_block(prov, "    ")
    m, dims = EMBEDDER_DEFAULTS[emb]
    m = a.embedder_model or m
    dims = a.embedder_dimensions or dims
    lines += ["", "embedder:"]
    if emb in ("ollama", "none"):
        url = base if emb == "ollama" else NO_LLM_URL
        lines += ["  provider: \"openai\"", f"  model: {yaml_str(m)}", f"  dimensions: {dims}", "  providers:",
                  "    openai:", f"      api_key: {yaml_str('ollama' if emb == 'ollama' else 'not-set')}",
                  f"      api_url: {yaml_str(url)}"]
    else:
        lines += [f"  provider: {yaml_str(emb)}", f"  model: {yaml_str(m)}", f"  dimensions: {dims}", "  providers:"]
        lines += provider_block(emb, "    ", embedder=True)
    lines += ["", "database:", "  provider: \"falkordb\"", "  providers:", "    falkordb:",
              "      uri: \"redis://localhost:6379\"", "      password: \"${FALKORDB_PASSWORD:}\"",
              "      database: \"${FALKORDB_DATABASE:default_db}\"", "",
              "graphiti:", "  group_id: \"${GRAPHITI_GROUP_ID:main}\"", "  episode_id_prefix: \"\"",
              "  user_id: \"testkit\"", "  entity_types:"]
    for n, d in ENTITY_TYPES:
        lines += [f"    - name: {yaml_str(n)}", f"      description: {yaml_str(d)}"]
    return "\n".join(lines) + "\n"


def provider_block(p, ind, embedder=False):
    b = {
        "openai": ["api_key: \"${OPENAI_API_KEY}\"", "api_url: \"${OPENAI_API_URL:https://api.openai.com/v1}\"",
                   "organization_id: \"${OPENAI_ORGANIZATION_ID:}\""],
        "anthropic": ["api_key: \"${ANTHROPIC_API_KEY}\"", "api_url: \"${ANTHROPIC_API_URL:https://api.anthropic.com}\"",
                      "max_retries: 3"],
        "gemini": ["api_key: \"${GOOGLE_API_KEY}\"", "project_id: \"${GOOGLE_PROJECT_ID:}\"",
                   "location: \"${GOOGLE_LOCATION:us-central1}\""],
        "groq": ["api_key: \"${GROQ_API_KEY}\"", "api_url: \"${GROQ_API_URL:https://api.groq.com/openai/v1}\""],
        "voyage": ["api_key: \"${VOYAGE_API_KEY}\"", "api_url: \"${VOYAGE_API_URL:https://api.voyageai.com/v1}\"",
                   "model: \"voyage-3\""],
        "azure_openai": ["api_key: \"${AZURE_OPENAI_API_KEY}\"",
                         ("api_url: \"${AZURE_OPENAI_EMBEDDINGS_ENDPOINT}\"" if embedder
                          else "api_url: \"${AZURE_OPENAI_ENDPOINT}\""),
                         "api_version: \"${AZURE_OPENAI_API_VERSION:2024-10-21}\"",
                         ("deployment_name: \"${AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT}\"" if embedder
                          else "deployment_name: \"${AZURE_OPENAI_DEPLOYMENT}\""),
                         "use_azure_ad: ${USE_AZURE_AD:false}"],
    }[p]
    return [f"{ind}{p}:"] + [f"{ind}  {x}" for x in b]


def render_compose(a) -> str:
    ports = [f"      - \"127.0.0.1:{a.port}:8000\"   # MCP server (HTTP)"]
    if a.expose_db:
        ports += ["      - \"127.0.0.1:6379:6379\"   # FalkorDB (Redis protocol)",
                  "      - \"127.0.0.1:3000:3000\"   # FalkorDB browser UI"]
    return f"""# Written by `testkit graph up` — adapted from getzep/graphiti mcp_server/docker/docker-compose.yml
# (Apache-2.0). FalkorDB + Graphiti MCP server in one container, reachable from this machine only.
name: {PROJECT}
services:
  graphiti:
    image: {IMAGE}
    container_name: {PROJECT}
    restart: unless-stopped
    env_file:
      - path: .env
        required: true
    environment:
      - GRAPHITI_TELEMETRY_ENABLED=false
      - BROWSER={1 if a.expose_db else 0}
      - FALKORDB_URI=redis://localhost:6379
      - CONFIG_PATH=/app/mcp/config/config.yaml
    volumes:
      - ./config.yaml:/app/mcp/config/config.yaml:ro
      - falkordb_data:/var/lib/falkordb/data
      - mcp_logs:/var/log/graphiti
    ports:
{chr(10).join(ports)}
    extra_hosts:
      - "host.docker.internal:host-gateway"   # lets the container reach Ollama on this machine (Linux)
    healthcheck:
      test: ["CMD-SHELL", "redis-cli -p 6379 ping >/dev/null && curl -fsS http://localhost:8000/health >/dev/null || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 6
      start_period: 30s

volumes:
  falkordb_data:
  mcp_logs:
"""


def write_private(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def wait_healthy(url, seconds):
    deadline = time.time() + seconds
    h = gd.health_url(url)
    while time.time() < deadline:
        if http_ok(h, 3):
            return True
        time.sleep(3)
    return False


def cmd_up(a):
    project = find_project(Path.cwd())
    if not a.force:
        r = gd.detect(project, config_url(project), timeout=2)
        if r["url"]:
            ok(f"Graphiti already reachable at {r['url']} ({r['source']}); reusing it")
            good, msg = mcp_status(r["url"])
            (ok if good else warn)(f"get_status: {msg}")
            return 0
    ver = need_docker()
    ok(f"docker compose {ver}")
    prov, emb = pick_provider(a)
    d = home_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "docker-compose.yml").write_text(render_compose(a), encoding="utf-8")
    (d / "config.yaml").write_text(render_config(prov, emb, a), encoding="utf-8")
    env_names = sorted(set(KEYS[prov] + EMB_KEYS[emb] + [k for k in OPTIONAL_ENV if os.environ.get(k)]))
    if os.environ.get("MODEL_NAME") and not a.model:
        env_names.append("MODEL_NAME")
    env_lines = ["# Written by `testkit graph up` from your environment. Do not commit or share.",
                 "GRAPHITI_TELEMETRY_ENABLED=false", f"SEMAPHORE_LIMIT={a.concurrency}"]
    env_lines += [f"{k}={os.environ[k]}" for k in env_names if os.environ.get(k)]
    write_private(d / ".env", "\n".join(env_lines) + "\n")
    (d / "testkit-graph.json").write_text(json.dumps({
        "provider": prov, "embedder": emb, "model": a.model, "image": IMAGE, "port": a.port,
        "url": f"http://localhost:{a.port}/mcp", "env_names": env_names,
        "local_llm": prov in ("ollama", "none") and emb in ("ollama", "none")}, indent=2) + "\n", encoding="utf-8")
    ok(f"wrote {d}/docker-compose.yml, config.yaml, .env (mode 600; variables: {', '.join(env_names) or 'none'})")
    print(f"  - LLM: {prov}{' / ' + a.model if a.model else ''}; embedder: {emb}")
    if prov not in ("ollama", "none") or emb not in ("ollama", "none"):
        print("  - note: content you add to the graph is sent to that provider's API for extraction/embeddings")
    have = run(["docker", "image", "inspect", IMAGE], check=False, capture=True).returncode == 0
    if not have:
        print(f"  - pulling {IMAGE} (about 3.7 GB download, ~11 GB on disk; one time)")
    compose("up", "-d", *(["--force-recreate"] if a.force else []))
    url = f"http://localhost:{a.port}/mcp"
    if a.no_wait:
        ok(f"started; MCP URL {url}")
        return 0
    if not wait_healthy(url, a.wait):
        warn(f"not healthy after {a.wait}s. Check: testkit graph logs")
        return 1
    ok(f"healthy: {gd.health_url(url)}")
    good, msg = mcp_status(url)
    (ok if good else warn)(f"get_status: {msg}")
    print(f"\n  MCP URL: {url}\n  Projects find it automatically (localhost probe). To let your coding agent use it "
          f"directly: testkit graph connect --agents claude,codex,gemini")
    return 0 if good else 1


# ---------- status / logs / down / uninstall ----------
def cmd_status(a):
    d = home_dir()
    meta = {}
    if (d / "testkit-graph.json").is_file():
        meta = json.loads((d / "testkit-graph.json").read_text(encoding="utf-8"))
        print(f"  local stack: {d}  (LLM {meta.get('provider')}, embedder {meta.get('embedder')}, image {meta.get('image')})")
        if shutil.which("docker"):
            r = compose("ps", "--format", "json", capture=True, check=False, timeout=30)
            rows = []
            for line in (r.stdout or "").splitlines():
                try:
                    v = json.loads(line)
                    rows += v if isinstance(v, list) else [v]
                except ValueError:
                    pass
            for c in rows:
                print(f"  container {c.get('Name')}: {c.get('State')} {c.get('Health') or ''} {c.get('Status') or ''}")
            if not rows:
                print("  container: not running (testkit graph up)")
    else:
        print(f"  no local stack in {d}")
    project = find_project(Path.cwd())
    r = gd.detect(project, config_url(project))
    if not r["url"]:
        warn("no reachable Graphiti")
        return 1
    ok(f"reachable: {r['url']} ({r['source']})")
    good, msg = mcp_status(r["url"])
    (ok if good else warn)(f"get_status: {msg}")
    return 0 if good else 1


def cmd_logs(a):
    compose("logs", "--no-color", "--tail", str(a.tail))
    return 0


def cmd_down(a):
    need_docker()
    compose("down")
    ok("stopped (graph data kept in the docker volume; testkit graph up starts it again)")
    return 0


def cmd_uninstall(a):
    d = home_dir()
    if (d / "docker-compose.yml").is_file() and shutil.which("docker"):
        compose("down", *(["-v"] if a.purge else []), check=False)
    if d.is_dir():
        shutil.rmtree(d)
    ok(f"removed {d}" + (" and the graph data volume" if a.purge else " (graph data volume kept; --purge removes it)"))
    print(f"  - the image {IMAGE} is kept; remove it with: docker image rm {IMAGE}")
    return 0


# ---------- connect ----------
def cmd_connect(a):
    url = a.url
    if not url:
        project = find_project(Path.cwd())
        url = gd.detect(project, config_url(project))["url"]
        if not url:
            die("No reachable Graphiti. Start one (testkit graph up) or pass --url.")
    url = gd.normalize_url(url)
    agents = [x.strip() for x in a.agents.split(",") if x.strip()]
    cmds = {
        "claude": ["claude", "mcp", "add", "--transport", "http", "--scope", "user", a.name, url],
        "codex": ["codex", "mcp", "add", a.name, "--url", url],
        "gemini": ["gemini", "mcp", "add", "--scope", "user", "--transport", "http", a.name, url],
    }
    status = 0
    for ag in agents:
        if ag in cmds:
            cmd = cmds[ag]
            if not shutil.which(cmd[0]):
                warn(f"{ag}: CLI '{cmd[0]}' not found; skipped")
                continue
            if a.dry_run:
                print("  would run: " + " ".join(cmd))
                continue
            r = run(cmd, check=False, capture=True, timeout=60)
            out = (r.stdout + r.stderr).strip()
            if r.returncode == 0:
                ok(f"{ag}: registered '{a.name}' → {url} (user scope)")
            elif "already exists" in out.lower():
                ok(f"{ag}: '{a.name}' already registered (remove it first to change the URL)")
            else:
                warn(f"{ag}: failed: {out[-300:]}")
                status = 1
        elif ag == "cursor":
            print(f"  cursor: add to ~/.cursor/mcp.json →  \"mcpServers\": {{\"{a.name}\": {{\"url\": \"{url}\"}}}}")
        elif ag == "copilot":
            print(f"  copilot: add to .vscode/mcp.json (or VS Code user settings) →  "
                  f"\"servers\": {{\"{a.name}\": {{\"type\": \"http\", \"url\": \"{url}\"}}}}")
        else:
            warn(f"unknown agent {ag!r} (claude, codex, gemini, cursor, copilot)")
    print("  - the URL holds no secret. When an agent calls the graph tools directly, it must pass the project's "
          "group_id (knowledge.group_id); testkit skills do this through kg.py.")
    return status


def main(argv=None):
    ap = argparse.ArgumentParser(prog="testkit graph", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("detect", help="print the reachable Graphiti MCP URL or 'none'")
    p.add_argument("--project", help="project root (default: nearest folder with qa/config.yml)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("up", help="start (or reuse) a local Graphiti")
    p.add_argument("--provider", choices=sorted(KEYS))
    p.add_argument("--model", help="LLM model name (required for anthropic, groq, ollama)")
    p.add_argument("--embedder", help="openai | gemini | voyage | azure_openai | ollama")
    p.add_argument("--embedder-model")
    p.add_argument("--embedder-dimensions", type=int)
    p.add_argument("--base-url", help=f"OpenAI-compatible URL for --provider/--embedder ollama (default {OLLAMA_URL})")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--expose-db", action="store_true", help="also bind FalkorDB 6379 and its UI 3000 on 127.0.0.1")
    p.add_argument("--concurrency", type=int, default=4, help="SEMAPHORE_LIMIT (episodes processed in parallel)")
    p.add_argument("--force", action="store_true", help="set up a local stack even if another Graphiti is reachable")
    p.add_argument("--no-wait", action="store_true")
    p.add_argument("--wait", type=int, default=240, help="seconds to wait for health (default 240)")
    sub.add_parser("status", help="local stack + reachable Graphiti + get_status")
    p = sub.add_parser("logs", help="container logs")
    p.add_argument("--tail", type=int, default=100)
    sub.add_parser("down", help="stop the local stack (keeps data)")
    p = sub.add_parser("connect", help="register the MCP URL with coding agents")
    p.add_argument("--agents", default="claude,codex,gemini")
    p.add_argument("--url")
    p.add_argument("--name", default="graphiti")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("uninstall", help="down + remove ~/.testkit/graphiti")
    p.add_argument("--purge", action="store_true", help="also delete the graph data volume")
    a = ap.parse_args(argv)
    return {"detect": cmd_detect, "up": cmd_up, "status": cmd_status, "logs": cmd_logs, "down": cmd_down,
            "connect": cmd_connect, "uninstall": cmd_uninstall}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
