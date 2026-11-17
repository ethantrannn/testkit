# /// script
# requires-python = ">=3.10"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""Run one read-only SQL query against a database from qa/config.yml and print masked results.

    uv run db_query.py --db main "SELECT id, status FROM orders WHERE note LIKE 'proj-123-s2%'"
    uv run db_query.py --db main --file check.sql --format json
    uv run db_query.py --db main "SELECT ..." --save qa/runs/PROJ-123/evidence/S2/TC-S2-004-db.md
    uv run db_query.py --db main --prove-readonly     # shows that a write is rejected
    uv run db_query.py --list

Config (qa/config.yml):
  data_checks:
    max_rows: 50                 # LIMIT applied to every query (override per call with --limit, max 1000)
    statement_timeout_s: 5
    mask_columns: [...]          # extra column-name patterns to mask
    databases:
      main:
        engine: postgres         # postgres | mysql | sqlite
        url_env: TESTKIT_DB_URL  # env var with the connection URL (use a read-only DB user)
        environment: staging     # must be an environment in qa/config.yml

Read-only, in three layers: (1) the statement must be a single SELECT / WITH / EXPLAIN (no ANALYZE) /
SHOW / DESCRIBE / read-only PRAGMA, with no write keyword anywhere; (2) the session is read-only:
postgres → PGOPTIONS default_transaction_read_only=on + BEGIN READ ONLY; mysql → START TRANSACTION
READ ONLY; sqlite → opened with mode=ro and PRAGMA query_only=ON; (3) a statement timeout and a row
LIMIT. Columns that look personal (email, phone, name, address, id numbers, tokens, ...) and any
e-mail address in the output are masked, except values of the test accounts in
qa/accounts.local.json. --no-mask prints raw values to the terminal only (not allowed with --save).
Clients: psql (postgres), mysql (mysql/mariadb); sqlite uses Python's built-in sqlite3 module.
Exit codes: 0 ok · 1 query rejected or failed · 2 usage/config error.
"""
import argparse
import csv
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

ALLOWED_START = {"SELECT", "WITH", "EXPLAIN", "SHOW", "DESCRIBE", "DESC", "PRAGMA", "VALUES", "TABLE"}
FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|UPSERT|REPLACE|CREATE|ALTER|DROP|TRUNCATE|RENAME|GRANT|REVOKE|"
    r"COPY|CALL|EXEC|EXECUTE|DO|LOCK|UNLOCK|VACUUM|ANALYZE|ATTACH|DETACH|REINDEX|CLUSTER|REFRESH|"
    r"COMMENT|SET|RESET|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|INTO|OUTFILE|DUMPFILE|LOAD|HANDLER|"
    r"NEXTVAL|SETVAL|PG_SLEEP|SLEEP|BENCHMARK|PG_TERMINATE_BACKEND|PG_CANCEL_BACKEND|LO_IMPORT|"
    r"LO_EXPORT|DBLINK|PG_READ_FILE|PG_WRITE_FILE|LOAD_FILE|LOAD_EXTENSION)\b", re.I)
PERSONAL = ["e_?mail", "mail", "phone", "mobile", "tel", "fax", "(first|last|full|display|user|given|family)_?name",
            "name", "address", "street", "dob", "birth(day|_?date)?", "ssn", "cccd", "cmnd", "national_?id",
            "id_?(number|no|card)", "passport", "tax(_?code|_?id)?", "iban", "account_?(no|number)",
            "card(_?number)?", "token", "secret", "password", "pwd", "hash", "salt", "ip(_?address)?", "otp"]
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def die(msg, code=2):
    print(f"db_query: {msg}", file=sys.stderr)
    sys.exit(code)


def project_root():
    for p in [Path.cwd(), *Path.cwd().parents]:
        if (p / "qa" / "config.yml").is_file():
            return p
    die("qa/config.yml not found (run from the project root)")


def strip_sql(sql, engine=""):
    """Remove comments and quoted literals so keyword checks only see SQL structure."""
    comment = r"--[^\n]*|#[^\n]*|/\*.*?\*/" if engine in ("mysql", "mariadb") else r"--[^\n]*|/\*.*?\*/"
    sql = re.sub(comment, " ", sql, flags=re.S)
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r'"(?:[^"]|"")*"', '""', sql)
    return re.sub(r"`[^`]*`", "``", sql)


def check_statement(sql, engine=""):
    bare = strip_sql(sql, engine).strip().rstrip(";").strip()
    if not bare:
        return "empty query"
    if ";" in bare:
        return "only one statement per call"
    first = bare.split(None, 1)[0].upper()
    if first not in ALLOWED_START:
        return f"{first} is not a read-only statement (allowed: SELECT, WITH, EXPLAIN, SHOW, DESCRIBE, PRAGMA)"
    if first == "EXPLAIN" and re.search(r"\bANALY[SZ]E\b", bare, re.I):
        return "EXPLAIN ANALYZE executes the statement; use plain EXPLAIN"
    if first == "PRAGMA" and "=" in bare:
        return "PRAGMA with '=' changes settings"
    m = FORBIDDEN.search(bare)
    if m and not (first == "EXPLAIN" and m.group(1).upper() == "ANALYZE"):
        return f"forbidden keyword {m.group(1).upper()}"
    if re.search(r"\bFOR\s+(UPDATE|SHARE|NO\s+KEY\s+UPDATE|KEY\s+SHARE)\b", bare, re.I):
        return "row locks (FOR UPDATE/SHARE) are not allowed"
    return None


def limited(sql, n):
    body = sql.strip().rstrip(";")
    first = strip_sql(body).split(None, 1)[0].upper()
    if first in {"SELECT", "WITH", "VALUES", "TABLE"}:
        return f"SELECT * FROM (\n{body}\n) AS tk_q LIMIT {n}"
    return body


def run_postgres(url, sql, timeout_s):
    psql = shutil.which("psql") or die("psql not found (macOS: brew install libpq · Debian/Ubuntu: "
                                       "apt install postgresql-client · Windows: winget install PostgreSQL.PostgreSQL.17)")
    env = dict(os.environ, PGCONNECT_TIMEOUT="10", PGAPPNAME="testkit-data-checks",
               PGOPTIONS=f"-c default_transaction_read_only=on -c statement_timeout={int(timeout_s * 1000)}")
    cmd = [psql, url, "-X", "-q", "--csv", "-v", "ON_ERROR_STOP=1",
           "-c", "BEGIN READ ONLY", "-c", sql, "-c", "ROLLBACK"]
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8")
    if p.returncode:
        die(f"postgres error: {p.stderr.strip()}", 1)
    rows = list(csv.reader(io.StringIO(p.stdout)))
    return (rows[0], rows[1:]) if rows else ([], [])


def run_mysql(url, sql, timeout_s):
    client = shutil.which("mysql") or shutil.which("mariadb") or die(
        "mysql client not found (macOS: brew install mysql-client · Debian/Ubuntu: apt install default-mysql-client "
        "· Windows: winget install Oracle.MySQL)")
    u = urlparse(url)
    cmd = [client, "--batch", "--connect-timeout=10", f"--host={u.hostname or 'localhost'}",
           f"--port={u.port or 3306}", f"--user={unquote(u.username or '')}", f"--database={u.path.lstrip('/')}"]
    env = dict(os.environ, MYSQL_PWD=unquote(u.password or ""))
    ms = int(timeout_s * 1000)
    script = (f"SET SESSION TRANSACTION READ ONLY;\n"
              f"SET SESSION max_execution_time={ms};\n" if "mariadb" not in client else
              f"SET SESSION TRANSACTION READ ONLY;\nSET SESSION max_statement_time={timeout_s};\n")
    script += f"START TRANSACTION READ ONLY;\n{sql};\nROLLBACK;\n"
    p = subprocess.run(cmd, input=script, env=env, capture_output=True, text=True, encoding="utf-8")
    if p.returncode:
        die(f"mysql error: {p.stderr.strip()}", 1)
    lines = [l.split("\t") for l in p.stdout.splitlines()]
    return (lines[0], lines[1:]) if lines else ([], [])


def run_sqlite(url, sql, timeout_s):
    path = re.sub(r"^sqlite:(//)?", "", url)          # sqlite:///abs/app.db, sqlite:rel.db, or a plain path
    if path.startswith("//"):
        path = path[1:]                                 # sqlite:////abs (SQLAlchemy style)
    if not Path(path).is_file() and path.startswith("/") and Path(path[1:]).is_file():
        path = path[1:]                                 # sqlite:///relative.db (SQLAlchemy style)
    if not Path(path).is_file():
        die(f"sqlite file not found: {path}")
    con = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True, timeout=timeout_s)
    try:
        con.execute("PRAGMA query_only = ON")
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description or []]
        return cols, [["" if v is None else str(v) for v in r] for r in cur.fetchall()]
    except sqlite3.Error as e:
        die(f"sqlite error: {e}", 1)
    finally:
        con.close()


RUNNERS = {"postgres": run_postgres, "postgresql": run_postgres, "mysql": run_mysql,
           "mariadb": run_mysql, "sqlite": run_sqlite}


def test_values(root):
    p = root / "qa" / "accounts.local.json"
    if not p.is_file():
        return set()
    found = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "email" and isinstance(v, str):
                    found.add(v.lower())
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    try:
        walk(json.loads(p.read_text(encoding="utf-8")))
    except ValueError:
        pass
    return found


def mask_value(v):
    if not v:
        return v
    if EMAIL_RE.fullmatch(v):
        return EMAIL_RE.sub(r"\1***@\2", v)
    digits = re.sub(r"\D", "", v)
    if len(digits) >= 6 and len(digits) >= len(v) * 0.6:
        return "*" * (len(v) - 3) + v[-3:]
    return v[0] + "***" if len(v) > 1 else "*"


def mask(cols, rows, extra, keep):
    pats = [re.compile(rf"(^|_)({p})(_|$)", re.I) for p in PERSONAL + list(extra)]
    personal = [any(p.search(c) for p in pats) for c in cols]
    out = []
    for r in rows:
        new = []
        for v, is_p in zip(r, personal):
            if v.lower() in keep:
                new.append(v)
            elif is_p:
                new.append(mask_value(v))
            else:
                new.append(EMAIL_RE.sub(lambda m: m.group(0) if m.group(0).lower() in keep
                                        else f"{m.group(1)}***@{m.group(2)}", v))
        out.append(new)
    return out


def render(cols, rows, fmt):
    if fmt == "json":
        return json.dumps([dict(zip(cols, r)) for r in rows], ensure_ascii=False, indent=2)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        w.writerows(rows)
        return buf.getvalue().rstrip("\n")
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(map(esc, cols)) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(map(esc, r)) + " |" for r in rows]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sql", nargs="?", help="the query (or use --file)")
    ap.add_argument("--db", help="database name under data_checks.databases")
    ap.add_argument("--file", help="read the query from this file")
    ap.add_argument("--limit", type=int, help="max rows (default data_checks.max_rows or 50; max 1000)")
    ap.add_argument("--format", choices=["table", "json", "csv"], default="table")
    ap.add_argument("--save", help="also write query + masked result as markdown evidence to this file")
    ap.add_argument("--no-mask", action="store_true", help="print raw values (terminal only)")
    ap.add_argument("--prove-readonly", action="store_true",
                    help="try a harmless write inside the read-only session and show it is rejected")
    ap.add_argument("--list", action="store_true", help="list configured databases")
    args = ap.parse_args()

    root = project_root()
    try:
        cfg = yaml.safe_load((root / "qa" / "config.yml").read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        die(f"qa/config.yml is not valid YAML: {e}")
    dc = cfg.get("data_checks") or {}
    dbs = dc.get("databases") or {}
    if args.list:
        for name, d in dbs.items():
            state = "set" if os.environ.get(d.get("url_env", "")) else "NOT SET"
            print(f"{name}\t{d.get('engine')}\t{d.get('environment')}\t{d.get('url_env')} ({state})")
        return 0
    if not args.db or args.db not in dbs:
        die(f"--db must be one of: {', '.join(dbs) or '(none configured under data_checks.databases)'}")
    d = dbs[args.db]
    engine = str(d.get("engine", "")).lower()
    if engine not in RUNNERS:
        die(f"engine '{engine}' not supported (postgres | mysql | sqlite)")
    if d.get("environment") not in (cfg.get("environments") or {}):
        die(f"database '{args.db}' must name an environment from qa/config.yml (environment: ...)")
    url = os.environ.get(d.get("url_env") or "")
    if not url:
        die(f"environment variable {d.get('url_env')} is not set (connection URL for '{args.db}')")
    timeout = float(dc.get("statement_timeout_s", 5))

    if args.prove_readonly:
        kind = RUNNERS[engine].__name__.split("_")[1]
        if kind == "mysql":   # DDL auto-commits in MySQL, so ask the session instead of writing
            _, rows = run_mysql(url, "SELECT @@session.transaction_read_only", timeout)
            if rows and rows[0][0] == "1":
                print("OK: session transaction_read_only = 1")
                return 0
            die("WARNING: the session is NOT read-only — do not use this connection", 1)
        probe = {"postgres": "CREATE TEMP TABLE tk_probe(x int)", "sqlite": "CREATE TABLE tk_probe(x int)"}[kind]
        print(f"probe (bypassing the statement filter, still inside the read-only session): {probe}")
        try:
            RUNNERS[engine](url, probe, timeout)
        except SystemExit as e:
            if e.code == 1:
                print("OK: the database rejected the write — this session is read-only")
                return 0
            raise
        die("WARNING: the write was NOT rejected — do not use this connection", 1)

    sql = Path(args.file).read_text(encoding="utf-8") if args.file else args.sql
    if not sql:
        die("give a query or --file")
    if problem := check_statement(sql, engine):
        die(f"rejected: {problem}", 1)
    if args.no_mask and args.save:
        die("--no-mask cannot be combined with --save (evidence must be masked)")
    limit = min(args.limit or int(dc.get("max_rows", 50)), 1000)
    cols, rows = RUNNERS[engine](url, limited(sql, limit + 1), timeout)
    truncated = len(rows) > limit
    rows = rows[:limit]
    is_data = strip_sql(sql, engine).split(None, 1)[0].upper() in {"SELECT", "WITH", "VALUES", "TABLE"}
    if is_data and not args.no_mask:   # schema output (PRAGMA, SHOW, DESCRIBE, EXPLAIN) is not personal
        rows = mask(cols, rows, dc.get("mask_columns") or [], test_values(root))
    out = render(cols, rows, args.format)
    note = f"{len(rows)} row(s)" + (f", truncated at {limit}" if truncated else "")
    print(out)
    print(note, file=sys.stderr)
    if args.save:
        p = Path(args.save)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"Database: {args.db} ({engine}, {d.get('environment')})\n\n```sql\n{sql.strip()}\n```\n\n"
                     f"{render(cols, rows, 'table')}\n\n{note}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
