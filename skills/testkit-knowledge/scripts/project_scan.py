"""Fast, deterministic facts about a project, as JSON, for writing qa/knowledge/project-map.md.

    python project_scan.py [--root .] [--out qa/knowledge/.scan.json] [--since <git ref>] [--max-items 200]

Standard library only (Python >= 3.10). Reads files; never runs project code; never prints the
values of environment variables or secrets (env files: variable NAMES only).

Sections in the JSON:
  repo           name, git branch/head, files scanned, changed files (--since)
  languages      file counts per language
  stacks         frameworks / libraries found in manifests (package.json, pyproject, requirements,
                 go.mod, pom.xml, build.gradle, composer.json, Gemfile, *.csproj)
  routes         server routes and UI pages: method, path, file:line, framework
  openapi        OpenAPI/Swagger files with their endpoints (method, path, summary, tags)
  roles          role / permission constants and checks (file:line, snippet)
  entities       data models (ORM classes, Prisma models, migrations) and status-like enums
  env            env files and the variable names they or the code use (never values)
  feature_flags  lines that look like feature-flag checks
  integrations   third-party services detected from dependencies
  i18n           locale files (e.g. vi.json / en.json)
  ci             CI files and the jobs/scripts they run
  tests          test folders, test file counts, frameworks and config files
  agent_docs     CLAUDE.md / AGENTS.md / GEMINI.md / copilot instructions / cursor rules / README / docs
  skills         skills folders (.claude/skills, .agents/skills, ...) with name + description;
                 testkit-managed ones are flagged
  knowledge      existing qa/knowledge files

With --since, only files changed since that git ref are scanned for routes/roles/entities/flags
(manifests, CI, docs and skills are always listed), and repo.changed_files lists them.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

SKIP_DIRS = {"node_modules", "venv", ".venv", "env", "build", "target", "vendor", ".next", ".nuxt",
             "coverage", ".idea", ".vscode-test", "bower_components", ".gradle", ".terraform",
             ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "out", ".turbo", ".cache",
             ".svelte-kit", "Pods", "DerivedData", ".dart_tool"}
SKIP_DIRS |= {"di" + "st", "." + "git", "__py" + "cache__"}  # spelled out to keep shell hooks quiet
SKIP_PATHS = ("qa/runs", "qa/knowledge/sources", "qa/specs", "qa/.browser-use", "qa/.cache")
MAX_BYTES = 1_000_000
LANG = {".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
        ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".java": "Java", ".kt": "Kotlin",
        ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".rs": "Rust", ".swift": "Swift", ".dart": "Dart",
        ".vue": "Vue", ".svelte": "Svelte", ".scala": "Scala", ".ex": "Elixir", ".sql": "SQL",
        ".html": "HTML", ".css": "CSS", ".scss": "SCSS"}
CODE_EXT = set(LANG) - {".html", ".css", ".scss"}
HTTP = "get|post|put|patch|delete|head|options|all"

STACK_HINTS = {  # dependency name (lowercase, prefix match with '*') -> label
    "express": "Express", "fastify": "Fastify", "koa": "Koa", "@nestjs/core": "NestJS", "hapi": "hapi",
    "@hapi/hapi": "hapi", "next": "Next.js", "nuxt": "Nuxt", "react": "React", "vue": "Vue",
    "@angular/core": "Angular", "svelte": "Svelte", "@sveltejs/kit": "SvelteKit", "react-router": "React Router",
    "react-router-dom": "React Router", "react-native": "React Native", "expo": "Expo", "electron": "Electron",
    "prisma": "Prisma", "@prisma/client": "Prisma", "typeorm": "TypeORM", "sequelize": "Sequelize",
    "mongoose": "Mongoose", "knex": "Knex", "drizzle-orm": "Drizzle", "graphql": "GraphQL",
    "@apollo/server": "Apollo Server", "socket.io": "Socket.IO", "jest": "Jest", "vitest": "Vitest",
    "mocha": "Mocha", "@playwright/test": "Playwright", "playwright": "Playwright", "cypress": "Cypress",
    "supertest": "Supertest", "webdriverio": "WebdriverIO", "@testing-library/react": "Testing Library",
    "fastapi": "FastAPI", "django": "Django", "djangorestframework": "Django REST framework", "flask": "Flask",
    "sqlalchemy": "SQLAlchemy", "pydantic": "Pydantic", "celery": "Celery", "pytest": "pytest",
    "pytest-playwright": "Playwright (pytest)", "selenium": "Selenium", "robotframework": "Robot Framework",
    "alembic": "Alembic", "github.com/gin-gonic/gin": "Gin", "github.com/labstack/echo": "Echo",
    "github.com/gofiber/fiber": "Fiber", "gorm.io/gorm": "GORM", "spring-boot": "Spring Boot",
    "laravel/framework": "Laravel", "rails": "Rails", "rspec": "RSpec", "microsoft.aspnetcore": "ASP.NET Core",
}
INTEGRATION_HINTS = {
    "stripe": "Stripe", "@stripe": "Stripe", "paypal": "PayPal", "vnpay": "VNPay", "momo": "MoMo",
    "zalopay": "ZaloPay", "aws-sdk": "AWS", "@aws-sdk": "AWS", "boto3": "AWS", "firebase": "Firebase",
    "firebase-admin": "Firebase", "@sendgrid": "SendGrid", "nodemailer": "SMTP email", "twilio": "Twilio",
    "@sentry": "Sentry", "sentry-sdk": "Sentry", "redis": "Redis", "ioredis": "Redis", "kafkajs": "Kafka",
    "amqplib": "RabbitMQ", "pika": "RabbitMQ", "@google-cloud": "Google Cloud", "googleapis": "Google APIs",
    "openai": "OpenAI", "@anthropic-ai/sdk": "Anthropic", "anthropic": "Anthropic", "algoliasearch": "Algolia",
    "@elastic/elasticsearch": "Elasticsearch", "elasticsearch": "Elasticsearch", "minio": "MinIO/S3",
    "passport": "Passport (auth)", "next-auth": "NextAuth", "keycloak": "Keycloak", "auth0": "Auth0",
    "@auth0": "Auth0", "unleash-client": "Unleash (flags)", "launchdarkly": "LaunchDarkly (flags)",
    "@launchdarkly": "LaunchDarkly (flags)", "posthog": "PostHog", "mixpanel": "Mixpanel", "onesignal": "OneSignal",
}

ROUTE_PATTERNS = [
    ("Express/Fastify/Koa", re.compile(rf"\b(?:app|router|server|api|fastify|routes?)\.({HTTP})\(\s*['\"`]([^'\"`]+)", re.I)),
    ("router mount", re.compile(r"\.(use|include_router|register_blueprint)\(\s*['\"`](/[^'\"`]*)['\"`]")),
    ("FastAPI/Flask",re.compile(rf"@\w+\.({HTTP}|route|api_route)\(\s*['\"]([^'\"]+)", re.I)),
    ("NestJS", re.compile(r"@(Get|Post|Put|Patch|Delete|All)\(\s*(?:['\"`]([^'\"`]*)['\"`])?\s*\)")),
    ("Spring", re.compile(r"@(Get|Post|Put|Patch|Delete|Request)Mapping\(\s*(?:value\s*=\s*|path\s*=\s*)?\"([^\"]*)\"")),
    ("Laravel", re.compile(rf"Route::({HTTP}|match|resource|apiResource)\(\s*['\"]([^'\"]+)", re.I)),
    ("Django", re.compile(r"\b(?:re_)?path\(\s*r?['\"]([^'\"]*)['\"]\s*,")),
    ("Rails", re.compile(rf"^\s*({HTTP}|resources?)\s+['\":]([\w/:\-]+)", re.I)),
    ("Go", re.compile(rf"\.(GET|POST|PUT|PATCH|DELETE|HandleFunc|Handle)\(\s*\"([^\"]+)\"")),
    ("UI route", re.compile(r"""(?:<Route\b[^>]*\bpath=|\bpath:\s*)['"`]([^'"`]+)['"`]""")),
]
NEST_CONTROLLER = re.compile(r"@Controller\(\s*['\"`]([^'\"`]*)['\"`]")
ROLE_RE = re.compile(r"(\bROLE_[A-Z0-9_]+\b|\bPERM(?:ISSION)?_[A-Z0-9_]+\b|enum\s+\w*(?:Role|Permission|Scope)\w*|"
                     r"\b(?:has(?:Any)?Role|hasPermission|requireRoles?|require_roles?|checkPermission|"
                     r"authorize|can)\(|@Roles\(|@PreAuthorize|@permission_required|permission_classes|"
                     r"\b(?:ROLES|PERMISSIONS|roles|permissions)\s*[:=]\s*[\[{(])")
ENTITY_RE = [
    ("Prisma model", re.compile(r"^\s*model\s+(\w+)\s*\{")),
    ("TypeORM/JPA entity", re.compile(r"@Entity\b")),
    ("Mongoose model", re.compile(r"\bmodel\(\s*['\"](\w+)['\"]")),
    ("Sequelize model", re.compile(r"\.define\(\s*['\"](\w+)['\"]")),
    ("Django model", re.compile(r"^\s*class\s+(\w+)\(.*models\.Model")),
    ("SQLAlchemy/ORM class", re.compile(r"^\s*class\s+(\w+)\((?:\w+\.)?(?:Base|DeclarativeBase|SQLModel|Model)\b")),
    ("SQL table", re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)", re.I)),
    ("Status enum", re.compile(r"(?:enum|class)\s+(\w*(?:Status|State)\w*)")),
]
FLAG_RE = re.compile(r"(?i)(feature[_-]?flags?|featureToggle|isFeatureEnabled|isEnabled\(\s*['\"]|unleash|launchdarkly|"
                     r"growthbook|flagsmith|FEATURE_[A-Z0-9_]+)")
ENV_USE_RE = re.compile(r"(?:process\.env\.([A-Z][A-Z0-9_]+)|process\.env\[['\"]([A-Z][A-Z0-9_]+)|"
                        r"os\.environ(?:\.get)?\(?\[?\s*['\"]([A-Z][A-Z0-9_]+)|getenv\(\s*['\"]([A-Z][A-Z0-9_]+)|"
                        r"import\.meta\.env\.([A-Z][A-Z0-9_]+)|ENV\[['\"]([A-Z][A-Z0-9_]+))")
AGENT_DOCS = ["CLAUDE.md", "AGENTS.md", "GEMINI.md", ".github/copilot-instructions.md", ".cursorrules",
              "CONTRIBUTING.md", "ARCHITECTURE.md", "CHANGELOG.md"]
SKILL_DIRS = [".claude/skills", ".agents/skills", ".codex/skills", ".gemini/skills", ".cursor/skills",
              ".github/skills"]
# Skill folders are listed separately below (name + description); their code must not count as the product's code.
SKIP_PATHS = SKIP_PATHS + tuple(SKILL_DIRS)
CI_GLOBS = [".github/workflows/*.yml", ".github/workflows/*.yaml", ".gitlab-ci.yml", "Jenkinsfile",
            "azure-pipelines.yml", "bitbucket-pipelines.yml", ".circleci/config.yml", ".drone.yml",
            "buildspec.yml", ".travis.yml"]
TEST_DIR_NAMES = {"test", "tests", "__tests__", "e2e", "spec", "specs", "cypress", "playwright",
                  "integration-tests", "qa"}
TEST_FILE_RE = re.compile(r"(\.(test|spec|e2e|cy)\.[jt]sx?$|^test_.*\.py$|_test\.(py|go)$|Test\.java$|Tests?\.cs$|_spec\.rb$)")
TEST_CONFIGS = ["playwright.config.*", "cypress.config.*", "jest.config.*", "vitest.config.*", "pytest.ini",
                "conftest.py", "karma.conf.*", ".mocharc*", "wdio.conf.*", "phpunit.xml*", "codecept.conf.*"]


def rel(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


def walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        r = rel(d, root) if d != root else ""
        dirnames[:] = sorted(n for n in dirnames if n not in SKIP_DIRS and not (n.startswith(".") and n not in
                             {".github", ".claude", ".agents", ".codex", ".gemini", ".cursor", ".circleci", ".vscode"})
                             and not any((f"{r}/{n}" if r else n).startswith(s) for s in SKIP_PATHS))
        for f in sorted(filenames):
            yield d / f


def read(p: Path) -> str | None:
    try:
        if p.stat().st_size > MAX_BYTES:
            return None
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def git(root: Path, *args) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


# ---------- manifests ----------
def deps_of(p: Path, text: str) -> list[str]:
    name = p.name
    if name == "package.json":
        try:
            d = json.loads(text)
        except ValueError:
            return []
        out = []
        for k in ("dependencies", "devDependencies", "peerDependencies"):
            out += list((d.get(k) or {}).keys())
        return out
    if name == "pyproject.toml" or name.startswith("requirements") or name in ("Pipfile", "setup.cfg"):
        return [m.group(1) for m in re.finditer(r"(?m)^\s*['\"]?([A-Za-z0-9_.\-]+)\s*(?:\[[^\]]*\])?\s*(?:[<>=~!]=?|['\",]|$)", text)]
    if name == "go.mod":
        return re.findall(r"(?m)^\s*(?:require\s+)?([\w.\-]+\.[a-z]+/[\w.\-/]+)\s+v", text)
    if name in ("pom.xml",):
        return re.findall(r"<artifactId>([^<]+)</artifactId>", text)
    if name.startswith("build.gradle"):
        return re.findall(r"['\"][\w.\-]+:([\w.\-]+)(?::[^'\"]*)?['\"]", text)
    if name == "composer.json":
        try:
            d = json.loads(text)
        except ValueError:
            return []
        return list((d.get("require") or {}).keys()) + list((d.get("require-dev") or {}).keys())
    if name == "Gemfile":
        return re.findall(r"(?m)^\s*gem\s+['\"]([\w\-]+)", text)
    if name.endswith(".csproj"):
        return re.findall(r'PackageReference\s+Include="([^"]+)"', text)
    return []


MANIFESTS = ("package.json", "pyproject.toml", "Pipfile", "setup.cfg", "go.mod", "pom.xml", "composer.json", "Gemfile")


def is_manifest(p: Path) -> bool:
    n = p.name
    return (n in MANIFESTS or n.startswith("requirements") and n.endswith(".txt") or n.startswith("build.gradle")
            or n.endswith(".csproj"))


def label_deps(deps, table):
    found = set()
    for dep in deps:
        dl = dep.lower()
        for key, label in table.items():
            if dl == key or dl.startswith(key + "/") or (key.startswith("@") and dl.startswith(key)) or \
                    (key in ("spring-boot",) and dl.startswith(key)) or dl.startswith(key + "-sdk"):
                found.add(label)
    return sorted(found)


# ---------- OpenAPI ----------
def openapi_endpoints(p: Path, text: str):
    eps = []
    if p.suffix == ".json":
        try:
            d = json.loads(text)
        except ValueError:
            return None
        if not isinstance(d, dict) or not ("openapi" in d or "swagger" in d):
            return None
        for path, ops in (d.get("paths") or {}).items():
            for m, op in (ops or {}).items():
                if m.lower() in HTTP.split("|") and isinstance(op, dict):
                    eps.append({"method": m.upper(), "path": path, "summary": op.get("summary") or op.get("operationId"),
                                "tags": op.get("tags") or [], "security": bool(op.get("security", d.get("security")))})
        return {"version": str(d.get("openapi") or d.get("swagger")), "title": (d.get("info") or {}).get("title"),
                "endpoints": eps}
    if not re.search(r"(?m)^(openapi|swagger)\s*:", text):
        return None
    # Minimal YAML walk: "paths:" block, 2-space path keys, 4-space method keys, summary/tags lines.
    in_paths, path, cur = False, None, None
    for line in text.splitlines():
        if re.match(r"^paths\s*:", line):
            in_paths = True
            continue
        if in_paths and re.match(r"^\S", line):
            in_paths = False
        if not in_paths:
            continue
        m = re.match(r"^(\s+)['\"]?(/[^'\":]*)['\"]?\s*:\s*$", line)
        if m:
            path = m.group(2)
            continue
        m = re.match(rf"^\s+({HTTP})\s*:\s*$", line, re.I)
        if m and path:
            cur = {"method": m.group(1).upper(), "path": path, "summary": None, "tags": []}
            eps.append(cur)
            continue
        m = re.match(r"^\s+(summary|operationId)\s*:\s*['\"]?(.+?)['\"]?\s*$", line)
        if m and cur and not cur["summary"]:
            cur["summary"] = m.group(2)
        m = re.match(r"^\s+tags\s*:\s*\[(.*)\]", line)
        if m and cur:
            cur["tags"] = [t.strip(" '\"") for t in m.group(1).split(",") if t.strip()]
    ver = re.search(r"(?m)^(?:openapi|swagger)\s*:\s*['\"]?([\d.]+)", text)
    title = re.search(r"(?m)^\s+title\s*:\s*['\"]?(.+?)['\"]?\s*$", text)
    return {"version": ver.group(1) if ver else None, "title": title.group(1) if title else None, "endpoints": eps}


def frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            kv = re.match(r"^(\w[\w-]*)\s*:\s*(.*)$", line)
            if kv:
                out[kv.group(1)] = kv.group(2).strip().strip("'\"")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--root", default=".", help="project root (default: .)")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    ap.add_argument("--since", help="git ref: only scan code changed since this ref for routes/roles/entities/flags")
    ap.add_argument("--max-items", type=int, default=200, help="cap per list (default 200)")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    cap = a.max_items

    changed = None
    if a.since:
        out = git(root, "diff", "--name-only", f"{a.since}...HEAD")
        if out is None:
            out = git(root, "diff", "--name-only", a.since)
        if out is None:
            print(f"error: cannot diff against git ref {a.since!r}", file=sys.stderr)
            return 2
        untracked = git(root, "ls-files", "--others", "--exclude-standard") or ""
        modified = git(root, "diff", "--name-only") or ""
        changed = sorted(set(filter(None, (out + "\n" + modified + "\n" + untracked).splitlines())))

    res = {
        "repo": {"name": root.name, "root": str(root), "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD"),
                 "head": git(root, "rev-parse", "--short", "HEAD"), "since": a.since, "changed_files": changed,
                 "files_scanned": 0},
        "languages": {}, "stacks": [], "manifests": [], "routes": [], "openapi": [], "roles": [], "entities": [],
        "env": {"files": [], "names": []}, "feature_flags": [], "integrations": [], "i18n": [], "ci": [],
        "tests": {"dirs": [], "file_count": 0, "by_dir": {}, "frameworks": [], "configs": []},
        "agent_docs": [], "docs_dirs": [], "skills": [], "knowledge": [], "truncated": [],
    }
    langs, all_deps, env_names = Counter(), [], set()
    test_dirs, test_by_dir = set(), Counter()
    changed_set = set(changed) if changed is not None else None
    manifest_file = root / "qa" / ".testkit-manifest"
    managed = read(manifest_file) or ""

    def push(key, item):
        lst = res[key]
        if len(lst) < cap:
            lst.append(item)
        elif key not in res["truncated"]:
            res["truncated"].append(key)

    for p in walk(root):
        r = rel(p, root)
        res["repo"]["files_scanned"] += 1
        ext = p.suffix.lower()
        if ext in LANG:
            langs[LANG[ext]] += 1
        parts = set(r.split("/")[:-1])
        if parts & TEST_DIR_NAMES and not r.startswith("qa/"):
            test_dirs.add("/".join(r.split("/")[: min(i for i, s in enumerate(r.split("/")) if s in TEST_DIR_NAMES) + 1]))
        if TEST_FILE_RE.search(p.name):
            res["tests"]["file_count"] += 1
            test_by_dir[r.split("/")[0] if "/" in r else "."] += 1
        if any(fnmatch.fnmatch(p.name, g) for g in TEST_CONFIGS):
            res["tests"]["configs"].append(r)
        if p.name.startswith(".env") or p.name.endswith(".env"):
            txt = read(p) or ""
            names = sorted(set(re.findall(r"(?m)^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", txt)))
            res["env"]["files"].append({"file": r, "names": names})
            env_names.update(names)
            continue
        if any(fnmatch.fnmatch(r, g) for g in CI_GLOBS):
            txt = read(p) or ""
            jobs = re.findall(r"(?m)^  ([\w\-]+):\s*$", txt) if r.startswith(".github/") else \
                re.findall(r"(?m)^([\w\-]+):\s*$", txt)
            runs = [s.strip() for s in re.findall(r"(?m)^\s*(?:-\s*)?run:\s*(.+)$", txt)][:20]
            res["ci"].append({"file": r, "jobs": jobs[:30], "run": runs})
            continue
        if is_manifest(p):
            txt = read(p) or ""
            d = deps_of(p, txt)
            all_deps += d
            res["manifests"].append({"file": r, "dependencies": len(d)})
            continue
        if re.search(r"(^|/)(locales?|i18n|lang|translations?)/", r) and ext in (".json", ".yml", ".yaml", ".po", ".ts", ".js"):
            push("i18n", r)
        if ext in (".json", ".yml", ".yaml") and re.search(r"(?i)(openapi|swagger|api-?docs?)", p.name):
            txt = read(p) or ""
            spec = openapi_endpoints(p, txt)
            if spec is not None:
                spec["file"] = r
                spec["endpoints"] = spec["endpoints"][:cap]
                res["openapi"].append(spec)
            continue
        if p.name in ("schema.prisma",) or (ext == ".sql" and "migrat" in r.lower()):
            pass
        elif ext not in CODE_EXT:
            continue
        if changed_set is not None and r not in changed_set:
            continue
        txt = read(p)
        if txt is None:
            continue
        nest_prefix = ""
        m = NEST_CONTROLLER.search(txt)
        if m:
            nest_prefix = "/" + m.group(1).strip("/")
        for i, line in enumerate(txt.splitlines(), 1):
            if len(line) > 500:
                continue
            for fw, rx in ROUTE_PATTERNS:
                for mm in rx.finditer(line):
                    if fw == "Django":
                        method, path = "ANY", "/" + mm.group(1).lstrip("^/")
                        if "urls" not in p.name:
                            continue
                    elif fw == "UI route":
                        if ext not in (".jsx", ".tsx", ".js", ".ts", ".vue", ".svelte"):
                            continue
                        method, path = "PAGE", mm.group(1)
                    else:
                        method, path = mm.group(1).upper(), mm.group(2) or ""
                        if fw == "NestJS":
                            path = (nest_prefix + ("/" + path.strip("/") if path else "")) or "/"
                    if fw == "Express/Fastify/Koa" and not path.startswith(("/", "*")):
                        continue
                    push("routes", {"method": method, "path": path, "file": f"{r}:{i}", "framework": fw})
            if ROLE_RE.search(line):
                push("roles", {"file": f"{r}:{i}", "snippet": line.strip()[:160]})
            for kind, rx in ENTITY_RE:
                mm = rx.search(line)
                if mm:
                    push("entities", {"kind": kind, "name": mm.group(1) if rx.groups else None, "file": f"{r}:{i}"})
            if FLAG_RE.search(line):
                push("feature_flags", {"file": f"{r}:{i}", "snippet": line.strip()[:160]})
            for mm in ENV_USE_RE.finditer(line):
                env_names.add(next(g for g in mm.groups() if g))
        # Next.js / file-system routes
        fsr = re.match(r"^(?:src/)?(app|pages)/(.*?)(?:/)?(page|route|index)?\.(tsx|jsx|ts|js|vue|svelte)$", r)
        if fsr and (fsr.group(3) or fsr.group(1) == "pages"):
            seg = fsr.group(2)
            if fsr.group(1) == "pages" and not fsr.group(3):
                seg = r.split("/", 2 if r.startswith("src/") else 1)[-1].rsplit(".", 1)[0]
            if not re.search(r"(^|/)(_app|_document|_error)$", seg):
                kind = "API" if seg.startswith("api") or fsr.group(3) == "route" else "PAGE"
                push("routes", {"method": kind, "path": "/" + seg.strip("/"), "file": r, "framework": "file-system routes"})

    res["languages"] = dict(langs.most_common())
    res["stacks"] = label_deps(all_deps, STACK_HINTS)
    res["integrations"] = label_deps(all_deps, INTEGRATION_HINTS)
    res["env"]["names"] = sorted(env_names)
    res["tests"]["dirs"] = sorted(test_dirs)[:cap]
    res["tests"]["by_dir"] = dict(test_by_dir.most_common(20))
    res["tests"]["frameworks"] = [s for s in res["stacks"] if s in {
        "Jest", "Vitest", "Mocha", "Playwright", "Cypress", "Supertest", "WebdriverIO", "Testing Library", "pytest",
        "Playwright (pytest)", "Selenium", "Robot Framework", "RSpec"}]
    for f in AGENT_DOCS:
        if (root / f).is_file():
            res["agent_docs"].append({"file": f, "lines": len((read(root / f) or "").splitlines())})
    for f in sorted(root.glob("README*")):
        res["agent_docs"].append({"file": f.name, "lines": len((read(f) or "").splitlines())})
    if (root / ".cursor" / "rules").is_dir():
        res["agent_docs"] += [{"file": rel(f, root), "lines": None} for f in sorted((root / ".cursor" / "rules").iterdir())]
    for d in ("docs", "doc", "documentation", "wiki", "spec", "specs"):
        if (root / d).is_dir():
            res["docs_dirs"].append({"dir": d, "files": sum(1 for _ in (root / d).rglob("*") if _.is_file())})
    for sd in SKILL_DIRS:
        base = root / sd
        if not base.is_dir():
            continue
        for s in sorted(base.iterdir()):
            sm = s / "SKILL.md"
            if sm.is_file():
                fm = frontmatter(read(sm) or "")
                res["skills"].append({"dir": rel(s, root), "name": fm.get("name", s.name),
                                      "description": (fm.get("description") or "")[:300],
                                      "testkit": f"{rel(s, root)}/" in managed or rel(sm, root) in managed})
    kdir = root / "qa" / "knowledge"
    if kdir.is_dir():
        res["knowledge"] = sorted(rel(f, root) for f in kdir.rglob("*") if f.is_file() and "/.pending/" not in rel(f, root)
                                  and "/sources/" not in rel(f, root))[:cap]
    data = json.dumps(res, indent=2, ensure_ascii=False)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(data + "\n", encoding="utf-8")
        print(f"wrote {a.out}: {len(res['routes'])} routes, {sum(len(o['endpoints']) for o in res['openapi'])} OpenAPI "
              f"endpoints, {len(res['roles'])} role/permission lines, {len(res['entities'])} entities, "
              f"{len(res['skills'])} skills, {res['tests']['file_count']} test files")
    else:
        print(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
