# /// script
# requires-python = ">=3.10"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""Run the Playwright suite in qa/automation against an environment from qa/config.yml.

    uv run run_suite.py [--env NAME] [--install] [-- <playwright test args>]

Examples (from the project root):
    uv run run_suite.py --install                       # npm ci + Chromium, then the full suite
    uv run run_suite.py -- --grep @smoke                # smoke suite
    uv run run_suite.py -- tests/PROJ-123/S1-login.spec.ts --project chromium
    uv run run_suite.py -- --list                       # list tests without running them

What it does:
  * TESTKIT_BASE_URL  <- environments.<env>.base_url (env = --env, else automation.environment,
                         else default_environment). Refuses hosts not in qa/config.yml and environments
                         with allow_write: false (the suite signs in and creates data).
  * TESTKIT_E2E_<ROLE>_EMAIL / _PASSWORD (/ _NAME) <- qa/accounts.local.json: "automation": {"<role>": {email,
    password}} first, else the newest executor account of that role under "runs". Variables already set
    in the environment win. Values are never printed.
  * Runs `npx playwright test <args>` inside qa/automation and exits with its exit code.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def die(msg, code=2):
    print(f"run_suite: {msg}", file=sys.stderr)
    sys.exit(code)


def env_key(role):
    return re.sub(r"[^A-Z0-9]", "_", role.upper())


def roles_from_setup(auto_dir):
    """Roles listed in tests/auth.setup.ts (const ROLES = ['member', 'admin'])."""
    f = auto_dir / "tests" / "auth.setup.ts"
    if not f.exists():
        return []
    m = re.search(r"ROLES\s*=\s*\[([^\]]*)\]", f.read_text(encoding="utf-8"))
    return re.findall(r"['\"]([^'\"]+)['\"]", m.group(1)) if m else []


def find_account(accounts, role):
    auto = (accounts.get("automation") or {}).get(role)
    if isinstance(auto, dict) and auto.get("email") and auto.get("password"):
        return auto
    best = None
    for run in (accounts.get("runs") or {}).values():
        for stream in (run or {}).values():
            for acc in stream if isinstance(stream, list) else [stream]:
                if isinstance(acc, dict) and acc.get("role") == role and acc.get("email") and acc.get("password"):
                    if best is None or str(acc.get("created_at", "")) >= str(best.get("created_at", "")):
                        best = acc
    return best


def run(cmd, cwd, env):
    exe = shutil.which(cmd[0])
    if not exe:
        die(f"{cmd[0]} not found. Install Node.js 20+ (it ships npm and npx).")
    return subprocess.call([exe, *cmd[1:]], cwd=cwd, env=env)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--env", help="environment name from qa/config.yml")
    ap.add_argument("--install", action="store_true", help="npm ci (or npm install) and install Chromium first")
    ap.add_argument("--root", default=".", help="project root (folder with qa/config.yml)")
    ap.add_argument("pw_args", nargs=argparse.REMAINDER, help="arguments after -- go to `playwright test`")
    a = ap.parse_args()
    pw_args = a.pw_args[1:] if a.pw_args[:1] == ["--"] else a.pw_args

    root = Path(a.root).resolve()
    cfg_file = root / "qa" / "config.yml"
    if not cfg_file.exists():
        die(f"{cfg_file} not found. Run from the project root (testkit init creates qa/config.yml).")
    cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    auto_cfg = cfg.get("automation") or {}
    auto_dir = root / (auto_cfg.get("dir") or "qa/automation")
    if not (auto_dir / "playwright.config.ts").exists():
        die(f"{auto_dir}/playwright.config.ts not found. Scaffold the suite first (testkit-automate skill).")

    env_name = a.env or auto_cfg.get("environment") or cfg.get("default_environment")
    envs = cfg.get("environments") or {}
    if env_name not in envs:
        die(f"environment {env_name!r} is not in qa/config.yml (known: {', '.join(envs) or 'none'})")
    env_cfg = envs[env_name] or {}
    base_url = env_cfg.get("base_url")
    if not base_url:
        die(f"environments.{env_name}.base_url is empty")
    if env_cfg.get("allow_write") is False:
        die(f"environment {env_name!r} has allow_write: false; the suite signs in and creates data. "
            "Pick another environment with --env.")

    env = dict(os.environ)
    env["TESTKIT_BASE_URL"] = base_url
    acc_file = root / "qa" / "accounts.local.json"
    accounts = json.loads(acc_file.read_text(encoding="utf-8")) if acc_file.exists() else {}
    roles = auto_cfg.get("roles") or roles_from_setup(auto_dir)
    filled, missing = [], []
    for role in roles:
        k = env_key(role)
        if env.get(f"TESTKIT_E2E_{k}_EMAIL") and env.get(f"TESTKIT_E2E_{k}_PASSWORD"):
            filled.append(f"{role} (from environment)")
            continue
        acc = find_account(accounts, role)
        if not acc:
            missing.append(role)
            continue
        env[f"TESTKIT_E2E_{k}_EMAIL"] = acc["email"]
        env[f"TESTKIT_E2E_{k}_PASSWORD"] = acc["password"]
        if acc.get("name"):
            env[f"TESTKIT_E2E_{k}_NAME"] = acc["name"]
        filled.append(f"{role} (from qa/accounts.local.json)")
    if missing:
        die("no account for role(s) " + ", ".join(missing) + ": add them to qa/accounts.local.json under "
            '"automation": {"<role>": {"email": ..., "password": ...}} or set TESTKIT_E2E_<ROLE>_EMAIL/_PASSWORD.')

    print(f"run_suite: environment {env_name} → {base_url}", flush=True)
    print(f"run_suite: accounts: {', '.join(filled) or 'none'}", flush=True)

    if a.install:
        lock = (auto_dir / "package-lock.json").exists()
        if run(["npm", "ci" if lock else "install"], auto_dir, env):
            die("npm install failed", 1)
        if run(["npx", "playwright", "install", "chromium"], auto_dir, env):
            die("playwright install chromium failed (on Linux CI use: npx playwright install --with-deps chromium)", 1)

    sys.exit(run(["npx", "playwright", "test", *pw_args], auto_dir, env))


if __name__ == "__main__":
    main()
