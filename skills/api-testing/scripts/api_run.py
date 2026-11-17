# /// script
# requires-python = ">=3.10"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""Run the Hurl files of one testkit stream and summarise the results.

    uv run api_run.py run   --run PROJ-123 --stream S2 [--env staging] [--case TC-S2-004 ...]
    uv run api_run.py check --run PROJ-123 --stream S2 [--env staging]
    uv run api_run.py vars  --run PROJ-123 --stream S2 [--env staging]

Commands
  run    Safety check (a file that fails it is not sent and becomes BLOCKED), then run every qa/runs/<RUN>/api/<STREAM>/<TC_ID>.hurl (or only --case)
         with `hurl --test`, one file at a time. Per case it writes
         qa/runs/<RUN>/evidence/<STREAM>/api/<TC_ID>/{report.json,store/,junit.xml,hurl.log}
         and then evidence/<STREAM>/api/summary.md (a markdown table of all cases run so far).
  check  Only the safety check: every request URL starts with {{base_url}} (or a host of a
         configured environment); on an environment with allow_write: false, no PUT/PATCH/DELETE,
         no GraphQL mutation, and POST only to api.read_only_posts.
  vars   Print the variables the files get (secrets shown as ***).

Variables given to every file
  base_url, run_id, stream_id, prefix (e.g. proj-123-s2, for test data names)
  <role>_email          from qa/accounts.local.json runs.<RUN>.<STREAM> (one per role; a 2nd
                        account of the same role becomes <role>2_email)
  <role>_password       secret, same source
  api.vars              plain values from qa/config.yml
  api.secrets_env       secret values read from the named environment variables
Plain variables go to a --variables-file (qa/runs/<RUN>/api/<STREAM>/.vars.env, no secrets);
secrets reach hurl only through HURL_SECRET_<name> in its environment, so Hurl redacts them
from logs and reports. Token-like JSON fields in saved responses are scrubbed as well.

Status per case: BLOCKED (failed the safety check, not sent) · PASS (exit 0) · FAIL (assert failed, exit 4) · ERROR (runtime error, exit 3:
host unreachable, capture failed — look at hurl.log) · CASE-ERROR (bad .hurl file, exit 2).
Exit code: 0 all PASS, 1 any other status, 2 usage/config error.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

WRITE_METHODS = {"PUT", "PATCH", "DELETE"}
METHOD_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)", re.M)
SECRET_KEYS = re.compile(
    r'("(?:[A-Za-z_]*token|password|secret|api_?key|otp|code_verifier)"\s*:\s*)"[^"]*"', re.I)


def die(msg, code=2):
    print(f"api_run: {msg}", file=sys.stderr)
    sys.exit(code)


def project_root():
    d = Path.cwd()
    for p in [d, *d.parents]:
        if (p / "qa" / "config.yml").is_file():
            return p
    die("qa/config.yml not found (run from the project root after `testkit init`)")


def load_config(root):
    try:
        return yaml.safe_load((root / "qa" / "config.yml").read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        die(f"qa/config.yml is not valid YAML: {e}")


def env_info(cfg, env):
    env = env or cfg.get("default_environment")
    envs = cfg.get("environments") or {}
    if env not in envs:
        die(f"environment '{env}' is not in qa/config.yml environments ({', '.join(envs)})")
    api = cfg.get("api") or {}
    base = (api.get("base_urls") or {}).get(env) or envs[env].get("base_url")
    if not base:
        die(f"no base URL for environment '{env}' (environments.{env}.base_url or api.base_urls.{env})")
    return env, base.rstrip("/"), bool(envs[env].get("allow_write", False)), api


def allowed_hosts(cfg):
    hosts = set()
    for e in (cfg.get("environments") or {}).values():
        if e.get("base_url"):
            hosts.add(urlparse(e["base_url"]).netloc)
    for u in ((cfg.get("api") or {}).get("base_urls") or {}).values():
        hosts.add(urlparse(u).netloc)
    return hosts


def accounts(root, run, stream):
    p = root / "qa" / "accounts.local.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        die(f"qa/accounts.local.json is not valid JSON: {e}")
    entry = ((data.get("runs") or {}).get(run) or {}).get(stream) or {}
    items = entry if isinstance(entry, list) else [
        dict(v, role=v.get("role", k)) if isinstance(v, dict) else {} for k, v in entry.items()]
    out, seen = {}, {}
    for a in items:
        role = re.sub(r"\W", "_", str(a.get("role", "")))
        if not role or not a.get("email"):
            continue
        seen[role] = seen.get(role, 0) + 1
        name = role if seen[role] == 1 else f"{role}{seen[role]}"
        out[name] = a
    return out


def build_vars(root, cfg, args):
    env, base, allow_write, api = env_info(cfg, args.env)
    plain = {"base_url": base, "run_id": args.run, "stream_id": args.stream,
             "prefix": f"{args.run}-{args.stream}".lower()}
    secret = {}
    for name, acc in accounts(root, args.run, args.stream).items():
        plain[f"{name}_email"] = acc["email"]
        if acc.get("password"):
            secret[f"{name}_password"] = acc["password"]
    for k, v in (api.get("vars") or {}).items():
        plain[k] = str(v)
    missing = []
    for k, envname in (api.get("secrets_env") or {}).items():
        if os.environ.get(envname):
            secret[k] = os.environ[envname]
        else:
            missing.append(f"{k} (env {envname})")
    return env, allow_write, api, plain, secret, missing


def case_files(root, args):
    d = root / "qa" / "runs" / args.run / "api" / args.stream
    if not d.is_dir():
        die(f"{d.relative_to(root)} does not exist — write the .hurl files first")
    files = sorted(d.glob("*.hurl"))
    if args.case:
        want = set(args.case)
        files = [f for f in files if f.stem in want]
        if missing := want - {f.stem for f in files}:
            die(f"no .hurl file for: {', '.join(sorted(missing))}")
    if not files:
        die(f"no .hurl files in {d.relative_to(root)}")
    return d, files


def safety_problems(cfg, files, allow_write, api):
    hosts = allowed_hosts(cfg)
    ro_posts = [p.rstrip("/") for p in api.get("read_only_posts") or []]
    problems = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        for m in METHOD_RE.finditer(text):
            method, url = m.group(1), m.group(2)
            line = text.count("\n", 0, m.start()) + 1
            where = f"{f.name}:{line}"
            if url.startswith("{{base_url}}"):
                path = url[len("{{base_url}}"):].split("?")[0].rstrip("/")
            elif url.startswith("http"):
                if urlparse(url).netloc not in hosts:
                    problems.append(f"{where}: host of {url} is not a configured environment")
                path = urlparse(url).path.rstrip("/")
            else:
                problems.append(f"{where}: URL must start with {{{{base_url}}}}: {url}")
                continue
            if not allow_write:
                if method in WRITE_METHODS:
                    problems.append(f"{where}: {method} on an allow_write: false environment")
                elif method == "POST" and path not in ro_posts:
                    problems.append(f"{where}: POST {path} is not in api.read_only_posts "
                                    "(allow_write: false environment)")
        if not allow_write and re.search(r"\bmutation\b", text):
            problems.append(f"{f.name}: GraphQL mutation on an allow_write: false environment")
    return problems


def scrub(folder, secrets):
    for p in folder.rglob("*"):
        if not p.is_file() or p.suffix not in {".json", ".xml", ".log", ".txt", ".html"}:
            continue
        try:
            t = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new = SECRET_KEYS.sub(r'\1"***"', t)
        for v in secrets.values():
            if len(v) >= 4:
                new = new.replace(v, "***")
        if new != t:
            p.write_text(new, encoding="utf-8")


def first_failure(report):
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    for f in data:
        for e in f.get("entries", []):
            for a in e.get("asserts", []):
                if not a.get("success") and a.get("message"):
                    lines = a["message"].splitlines()
                    detail = " ".join(l.split("|", 1)[-1].strip(" ^") for l in lines[1:]
                                      if "actual" in l or "expected" in l)
                    return f"line {a.get('line')}: {lines[0]}: {detail}".strip(": ")
    return ""


STATUS = {0: "PASS", 4: "FAIL", 3: "ERROR", 2: "CASE-ERROR"}


def write_summary(ev_root, args):
    rows = []
    for d in sorted(p for p in ev_root.iterdir() if p.is_dir()):
        meta = d / "result.json"
        if meta.is_file():
            rows.append(json.loads(meta.read_text(encoding="utf-8")))
    tot = {}
    for r in rows:
        tot[r["status"]] = tot.get(r["status"], 0) + 1
    lines = [f"# API results — {args.run} {args.stream}", "",
             f"- Environment: {rows[0]['env']} {rows[0]['base_url']}" if rows else "",
             "- Totals: " + " · ".join(f"{k} {v}" for k, v in sorted(tot.items())), "",
             "| Case | Status | Requests | Time (ms) | Evidence | Detail |", "|---|---|---|---|---|---|"]
    for r in rows:
        detail = r["detail"].replace("|", "\\|")
        lines.append(f"| {r['case']} | {r['status']} | {r['requests']} | {r['time_ms']} | "
                     f"evidence/{args.stream}/api/{r['case']}/ | {detail} |")
    (ev_root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "\n".join(lines)


def cmd_run(root, cfg, args):
    env, allow_write, api, plain, secret, missing = build_vars(root, cfg, args)
    case_dir, files = case_files(root, args)
    used = "".join(f.read_text(encoding="utf-8") for f in files)
    if needed := [m for m in missing if "{{%s}}" % m.split()[0] in used.replace(" ", "")]:
        die("missing environment variables for api.secrets_env: " + ", ".join(needed))
    blocked = {}
    for pr in safety_problems(cfg, files, allow_write, api):
        blocked.setdefault(pr.split(":", 1)[0], pr)
    hurl = shutil.which("hurl")
    if not hurl:
        die("hurl is not installed (macOS: brew install hurl · Windows: winget install Orange-OpenSource.Hurl "
            "· Linux: see https://hurl.dev/docs/installation.html)")
    varfile = case_dir / ".vars.env"
    varfile.write_text("".join(f"{k}={v}\n" for k, v in plain.items()), encoding="utf-8")
    henv = {k: v for k, v in os.environ.items() if not k.startswith(("HURL_SECRET_", "HURL_VARIABLE_"))}
    henv.update({f"HURL_SECRET_{k}": v for k, v in secret.items()})
    ev_root = root / "qa" / "runs" / args.run / "evidence" / args.stream / "api"
    ev_root.mkdir(parents=True, exist_ok=True)
    jobs, delay = str(api.get("max_parallel", 1)), str(api.get("delay_ms", 100))
    for f in files:
        ev = ev_root / f.stem
        shutil.rmtree(ev, ignore_errors=True)
        ev.mkdir(parents=True)
        if f.name in blocked:
            detail = "safety: " + blocked[f.name].split(": ", 1)[1]
            (ev / "result.json").write_text(json.dumps(
                {"case": f.stem, "status": "BLOCKED", "requests": 0, "time_ms": 0, "detail": detail,
                 "env": env, "base_url": plain["base_url"]}, ensure_ascii=False), encoding="utf-8")
            print(f"{f.stem}: BLOCKED — {detail}", file=sys.stderr)
            continue
        cmd = [hurl, "--test", "--jobs", jobs, "--delay", delay, "--variables-file", str(varfile),
               "--report-json", str(ev), "--report-junit", str(ev / "junit.xml"),
               "--error-format", "long", "--file-root", str(case_dir), str(f)]
        cmd[1:1] = api.get("hurl_args") or []
        p = subprocess.run(cmd, cwd=root, env=henv, capture_output=True, text=True, encoding="utf-8")
        (ev / "hurl.log").write_text(p.stdout + p.stderr, encoding="utf-8")
        scrub(ev, secret)
        status = STATUS.get(p.returncode, f"ERROR({p.returncode})")
        report, nreq, t = ev / "report.json", 0, 0
        if report.is_file():
            data = json.loads(report.read_text(encoding="utf-8"))
            nreq = sum(len(x.get("entries", [])) for x in data)
            t = sum(x.get("time", 0) for x in data)
        detail = first_failure(report) if status == "FAIL" else ""
        if status != "PASS" and not detail:
            errs = [l for l in (p.stderr or "").splitlines() if l.startswith("error")]
            detail = errs[0][:200] if errs else "see hurl.log"
        (ev / "result.json").write_text(json.dumps(
            {"case": f.stem, "status": status, "requests": nreq, "time_ms": t, "detail": detail,
             "env": env, "base_url": plain["base_url"]}, ensure_ascii=False), encoding="utf-8")
        print(f"{f.stem}: {status}" + (f" — {detail}" if detail else ""), file=sys.stderr)
    summary = write_summary(ev_root, args)
    print(summary)
    results = [json.loads((ev_root / f.stem / "result.json").read_text(encoding="utf-8"))["status"]
               for f in files]
    return 0 if all(s == "PASS" for s in results) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["run", "check", "vars"])
    ap.add_argument("--run", required=True, help="RUN_ID")
    ap.add_argument("--stream", required=True, help="STREAM_ID")
    ap.add_argument("--env", help="environment name (default: default_environment)")
    ap.add_argument("--case", action="append", help="only this TC_ID (repeatable)")
    args = ap.parse_args()
    root = project_root()
    cfg = load_config(root)
    if args.command == "vars":
        _, _, _, plain, secret, missing = build_vars(root, cfg, args)
        for k, v in plain.items():
            print(f"{k}={v}")
        for k in secret:
            print(f"{k}=*** (secret)")
        for m in missing:
            print(f"MISSING {m}")
        return 1 if missing else 0
    if args.command == "check":
        _, allow_write, api, *_ = build_vars(root, cfg, args)
        _, files = case_files(root, args)
        probs = safety_problems(cfg, files, allow_write, api)
        print("\n".join(probs) if probs else f"OK: {len(files)} file(s) pass the safety check")
        return 1 if probs else 0
    return cmd_run(root, cfg, args)


if __name__ == "__main__":
    sys.exit(main())
