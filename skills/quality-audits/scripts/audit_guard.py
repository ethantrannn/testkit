# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""Decide whether an audit may run against an environment, from qa/config.yml.

    uv run audit_guard.py KIND ENV [--config qa/config.yml]

KIND: a11y | performance | visual | headers | load | security
  a11y, performance, visual, headers  allowed on any environment listed in `environments`
                                      (they only browse / send a few GET requests)
  load, security                      allowed only when ENV is in audits.<kind>.allowed_envs
                                      and is not a production environment

An environment counts as production when `production: true` is set on it or its name is
prod, production, prd or live. Production is refused for load and security whatever the config says.

Prints JSON: {"allowed": bool, "kind", "env", "base_url", "host", "settings": audits.<kind>, "reason"}.
Exit codes: 0 allowed, 3 refused, 2 usage or config error.
"""
import argparse
import json
import sys
from urllib.parse import urlparse

import yaml

LIGHT = {"a11y", "performance", "visual", "headers"}
HEAVY = {"load", "security"}
PROD_NAMES = {"prod", "production", "prd", "live"}


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__.split("\n\n", 1)[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("kind", choices=sorted(LIGHT | HEAVY))
    p.add_argument("env")
    p.add_argument("--config", default="qa/config.yml")
    a = p.parse_args()
    try:
        cfg = yaml.safe_load(open(a.config, encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        print(f"audit_guard: cannot read {a.config}: {e}", file=sys.stderr)
        return 2
    envs = cfg.get("environments") or {}
    audits = cfg.get("audits") or {}
    settings = audits.get(a.kind) or {}
    out = {"allowed": False, "kind": a.kind, "env": a.env, "base_url": None, "host": None, "settings": settings}

    env = envs.get(a.env)
    if not isinstance(env, dict) or not env.get("base_url"):
        out["reason"] = f"environment '{a.env}' is not in qa/config.yml environments ({', '.join(envs) or 'none'})"
        print(json.dumps(out, indent=2))
        return 3
    out["base_url"] = env["base_url"].rstrip("/")
    out["host"] = urlparse(env["base_url"]).netloc
    is_prod = bool(env.get("production")) or a.env.lower() in PROD_NAMES

    if a.kind in HEAVY:
        allowed_envs = settings.get("allowed_envs") or []
        if is_prod:
            out["reason"] = f"'{a.env}' is a production environment; {a.kind} audits never run on production"
        elif a.env not in allowed_envs:
            out["reason"] = (f"'{a.env}' is not in audits.{a.kind}.allowed_envs ({allowed_envs or 'empty'}); "
                             f"ask the user to add it to qa/config.yml")
        else:
            out["allowed"] = True
            out["reason"] = f"'{a.env}' is listed in audits.{a.kind}.allowed_envs"
    else:
        out["allowed"] = True
        out["reason"] = "light audit; environment is listed in qa/config.yml"
        if is_prod:
            out["reason"] += " (production: read-only browsing only, no throttled load loops)"
    print(json.dumps(out, indent=2))
    return 0 if out["allowed"] else 3


if __name__ == "__main__":
    sys.exit(main())
