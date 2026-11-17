#!/usr/bin/env python3
"""Read test emails from a Mailpit (or MailHog) inbox: wait for a message, extract an OTP or a link.

    python3 mailbox.py wait  --to ADDR [--subject RE] [--body RE] [--timeout 60] [--save FILE]
    python3 mailbox.py otp   --to ADDR [--pattern '\\b\\d{6}\\b'] [--subject RE] [--timeout 60]
    python3 mailbox.py link  --to ADDR [--pattern RE] [--subject RE] [--timeout 60]
    python3 mailbox.py list  [--to ADDR] [--limit 20]
    python3 mailbox.py show  --id ID [--part text|html|json]
    python3 mailbox.py purge --to ADDR            # delete only this address's messages

Inbox URL: --url, else env TESTKIT_INBOX_URL, else `accounts.inbox.url` in qa/config.yml.
Basic auth (optional): env named by `accounts.inbox.auth_env` (value "user:password"), or --auth-env.
Kind: `accounts.inbox.kind` (mailpit | mailhog), else detected (Mailpit answers /api/v1/info).

wait/otp/link poll every --interval seconds until a message to ADDR arrives that was received
within the last --since seconds (default 900) and matches --subject/--body (Python regexes,
case-insensitive). The newest match wins. Output: wait → JSON summary; otp → the code (first
capture group if the pattern has one, else the whole match); link → the URL. --save writes the
message (subject, from, to, date, text, links) as JSON evidence.
Exit codes: 0 found · 1 timed out / no match · 2 usage, config or connection error.
Standard library only (Python 3.9+).
"""
import argparse
import base64
import email
import email.header
import email.policy
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LINK_RE = re.compile(r"""https?://[^\s"'<>]+""")


def die(msg, code=2):
    print(f"mailbox: {msg}", file=sys.stderr)
    sys.exit(code)


def inbox_config():
    """Read accounts.inbox.{url,kind,auth_env} from qa/config.yml (flat keys, no YAML lib)."""
    for d in [Path.cwd(), *Path.cwd().parents]:
        p = d / "qa" / "config.yml"
        if p.is_file():
            break
    else:
        return {}
    out, path = {}, []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        m = re.match(r"\s*([\w-]+):\s*(.*)$", line)
        if not m:
            continue
        while path and path[-1][0] >= indent:
            path.pop()
        key, val = m.group(1), m.group(2).strip().strip("'\"")
        keys = [k for _, k in path]
        if keys == ["accounts", "inbox"] and val:
            out[key] = val
        if not val:
            path.append((indent, key))
    return out


class Inbox:
    def __init__(self, url, kind, auth):
        self.url, self.auth = url.rstrip("/"), auth
        self.kind = kind or self.detect()

    def req(self, path, method="GET", body=None, raw=False):
        r = urllib.request.Request(self.url + path, method=method,
                                   data=json.dumps(body).encode() if body is not None else None)
        r.add_header("Accept", "application/json")
        if body is not None:
            r.add_header("Content-Type", "application/json")
        if self.auth:
            r.add_header("Authorization", "Basic " + base64.b64encode(self.auth.encode()).decode())
        try:
            with urllib.request.urlopen(r, timeout=15) as resp:
                data = resp.read()
        except urllib.error.HTTPError as e:
            die(f"{method} {path} → HTTP {e.code}")
        except (urllib.error.URLError, OSError) as e:
            die(f"cannot reach inbox {self.url}: {e}")
        if raw:
            return data.decode("utf-8", "replace")
        return json.loads(data or b"null")

    def detect(self):
        try:
            with urllib.request.urlopen(self.url + "/api/v1/info", timeout=5) as r:
                if r.status == 200:
                    return "mailpit"
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return "mailpit"
        except (urllib.error.URLError, OSError) as e:
            die(f"cannot reach inbox {self.url}: {e}")
        return "mailhog"

    # Each returns a list of {id, subject, from, to, created(datetime)} newest first.
    def search(self, to=None, limit=50):
        if self.kind == "mailpit":
            if to:
                q = urllib.parse.urlencode({"query": f'to:"{to}"', "limit": limit})
                data = self.req(f"/api/v1/search?{q}")
            else:
                data = self.req(f"/api/v1/messages?limit={limit}")
            return [{"id": m["ID"], "subject": m.get("Subject", ""),
                     "from": (m.get("From") or {}).get("Address", ""),
                     "to": [a.get("Address", "") for a in m.get("To") or []],
                     "created": parse_time(m.get("Created"))} for m in data.get("messages") or []]
        if to:
            q = urllib.parse.urlencode({"kind": "to", "query": to, "limit": limit})
            data = self.req(f"/api/v2/search?{q}")
        else:
            data = self.req(f"/api/v2/messages?limit={limit}")
        out = []
        for m in data.get("items") or []:
            h = (m.get("Content") or {}).get("Headers") or {}
            out.append({"id": m["ID"], "subject": decode_header((h.get("Subject") or [""])[0]),
                        "from": (h.get("From") or [""])[0], "to": h.get("To") or [],
                        "created": parse_time(m.get("Created"))})
        return out

    def message(self, mid):
        """{id, subject, from, to, date, text, html}"""
        if self.kind == "mailpit":
            m = self.req(f"/api/v1/message/{urllib.parse.quote(mid)}")
            return {"id": m["ID"], "subject": m.get("Subject", ""),
                    "from": (m.get("From") or {}).get("Address", ""),
                    "to": [a.get("Address", "") for a in m.get("To") or []],
                    "date": m.get("Date", ""), "text": m.get("Text", ""), "html": m.get("HTML", "")}
        m = self.req(f"/api/v1/messages/{urllib.parse.quote(mid)}")
        msg = email.message_from_string((m.get("Raw") or {}).get("Data", ""), policy=email.policy.default)
        text = html_part = ""
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.is_multipart() or part.get_content_disposition() == "attachment":
                continue
            if ctype == "text/plain" and not text:
                text = part.get_content()
            elif ctype == "text/html" and not html_part:
                html_part = part.get_content()
        return {"id": m["ID"], "subject": str(msg.get("Subject", "")), "from": str(msg.get("From", "")),
                "to": [str(msg.get("To", ""))], "date": str(msg.get("Date", "")),
                "text": text, "html": html_part}

    def delete(self, ids):
        if not ids:
            return
        if self.kind == "mailpit":
            self.req("/api/v1/messages", method="DELETE", body={"IDs": ids}, raw=True)
        else:
            for i in ids:
                self.req(f"/api/v1/messages/{urllib.parse.quote(i)}", method="DELETE", raw=True)


def parse_time(s):
    if not s:
        return None
    s = re.sub(r"(\.\d{6})\d+", r"\1", s.replace("Z", "+00:00"))
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def decode_header(s):
    try:
        return str(email.header.make_header(email.header.decode_header(s)))
    except Exception:
        return s


def addressed_to(summary, addr):
    """Exact (case-insensitive) recipient match; search APIs match substrings."""
    return addr.lower() in [a.lower() for _, a in email.utils.getaddresses(summary["to"])]


def body_text(m):
    """Plain text of a message: the text part, else the HTML with tags removed."""
    if m["text"].strip():
        return m["text"]
    return html.unescape(re.sub(r"<[^>]+>", " ", m["html"]))


def links(m):
    found = re.findall(r"""href=["']([^"']+)["']""", m["html"] or "", re.I)
    found += LINK_RE.findall(m["text"] or "")
    out = []
    for u in found:
        u = html.unescape(u).rstrip(").,;")
        if u.startswith("http") and u not in out:
            out.append(u)
    return out


def wait_for(box, args):
    deadline = time.monotonic() + args.timeout
    subj = re.compile(args.subject, re.I) if args.subject else None
    body = re.compile(args.body, re.I | re.S) if getattr(args, "body", None) else None
    while True:
        now = datetime.now(timezone.utc)
        for s in box.search(args.to):
            if s["created"] and (now - s["created"]).total_seconds() > args.since:
                continue
            if not addressed_to(s, args.to) or (subj and not subj.search(s["subject"])):
                continue
            m = box.message(s["id"])
            if body and not (body.search(body_text(m)) or body.search(m["html"] or "")):
                continue
            if args.extract and not args.extract(m):
                continue
            return m
        if time.monotonic() >= deadline:
            what = f"to {args.to}" + (f", subject /{args.subject}/" if args.subject else "")
            die(f"no message {what} within {args.timeout}s", 1)
        time.sleep(args.interval)


def save(m, path):
    rec = {k: m[k] for k in ("id", "subject", "from", "to", "date")}
    rec["text"], rec["links"] = body_text(m)[:5000], links(m)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="inbox base URL (default: TESTKIT_INBOX_URL or accounts.inbox.url)")
    ap.add_argument("--kind", choices=["mailpit", "mailhog"], help="default: accounts.inbox.kind or auto")
    ap.add_argument("--auth-env", help="env var holding 'user:password' for basic auth")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("wait", "otp", "link"):
        p = sub.add_parser(name)
        p.add_argument("--to", required=True, help="recipient address (the test account's email)")
        p.add_argument("--subject", help="regex the subject must match")
        p.add_argument("--body", help="regex the text or HTML body must match")
        p.add_argument("--timeout", type=float, default=60, help="seconds to wait (default 60)")
        p.add_argument("--interval", type=float, default=2, help="poll interval seconds (default 2)")
        p.add_argument("--since", type=float, default=900,
                       help="ignore messages received more than N seconds ago (default 900)")
        p.add_argument("--save", help="write the message as JSON evidence to this file")
        if name == "otp":
            p.add_argument("--pattern", default=r"\b(\d{6})\b", help=r"OTP regex (default '\b(\d{6})\b')")
        if name == "link":
            p.add_argument("--pattern", default=r"https?://\S+", help="regex the link must match")
    p = sub.add_parser("list")
    p.add_argument("--to")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("show")
    p.add_argument("--id", required=True, help="message ID (Mailpit also accepts 'latest')")
    p.add_argument("--part", choices=["text", "html", "json"], default="text")
    p = sub.add_parser("purge")
    p.add_argument("--to", required=True, help="delete only messages to this address")
    args = ap.parse_args()

    cfg = inbox_config()
    url = args.url or os.environ.get("TESTKIT_INBOX_URL") or cfg.get("url")
    if not url:
        die("no inbox URL: set accounts.inbox.url in qa/config.yml, TESTKIT_INBOX_URL, or --url")
    auth_env = args.auth_env or cfg.get("auth_env")
    auth = os.environ.get(auth_env) if auth_env else None
    if auth_env and not auth:
        die(f"environment variable {auth_env} (inbox basic auth) is not set")
    box = Inbox(url, args.kind or cfg.get("kind"), auth)

    if args.cmd == "list":
        for s in box.search(args.to, args.limit):
            when = s["created"].isoformat(timespec="seconds") if s["created"] else ""
            print(f"{s['id']}\t{when}\t{','.join(s['to'])}\t{s['subject']}")
        return 0
    if args.cmd == "show":
        m = box.message(args.id)
        print(json.dumps(m, ensure_ascii=False, indent=2) if args.part == "json" else m[args.part])
        return 0
    if args.cmd == "purge":
        ids = [s["id"] for s in box.search(args.to, 500) if addressed_to(s, args.to)]
        box.delete(ids)
        print(f"deleted {len(ids)} message(s) to {args.to}")
        return 0

    pat = re.compile(args.pattern) if args.cmd in ("otp", "link") else None
    if args.cmd == "otp":
        args.extract = lambda m: pat.search(body_text(m)) or pat.search(m["subject"])
    elif args.cmd == "link":
        args.extract = lambda m: [u for u in links(m) if pat.search(u)]
    else:
        args.extract = None
    m = wait_for(box, args)
    if args.save:
        save(m, args.save)
    if args.cmd == "otp":
        hit = pat.search(body_text(m)) or pat.search(m["subject"])
        print(hit.group(1) if hit.groups() else hit.group(0))
    elif args.cmd == "link":
        print([u for u in links(m) if pat.search(u)][0])
    else:
        print(json.dumps({k: m[k] for k in ("id", "subject", "from", "to", "date")}
                         | {"links": links(m)[:10]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
