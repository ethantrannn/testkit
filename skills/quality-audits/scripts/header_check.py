#!/usr/bin/env python3
"""Quick passive security checks for a web app (stdlib only, a handful of GET/OPTIONS requests).

    python3 header_check.py URL [URL ...] [--probe] [--origin https://evil.example] [--json OUT.json]

Per URL: security headers (HSTS, CSP, X-Content-Type-Options, frame protection, Referrer-Policy,
Permissions-Policy), version leaks (Server, X-Powered-By), Set-Cookie flags (Secure, HttpOnly,
SameSite), CORS (does the API reflect an arbitrary Origin, with credentials?), HTTP -> HTTPS
redirect, TLS protocol and certificate expiry.
--probe   also GET a short list of well-known debug/secret paths (/.env, /actuator/env, …) on the
          first URL's origin. Only on environments in audits.security.allowed_envs; never production.

Each finding has a severity (blocker | critical | major | minor | trivial | info) ready for a bug.
Exit codes: 0 no finding above minor, 1 at least one major or worse, 2 usage or connection error.
"""
import argparse
import datetime as dt
import json
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)  # TLSv1/1.1 probes

UA = "testkit-header-check/1.0"
PROBE_PATHS = ["/.env", "/.git/config", "/actuator/env", "/actuator/heapdump", "/server-status", "/phpinfo.php",
               "/debug", "/__debug__/", "/.DS_Store", "/config.json", "/swagger-ui/", "/v3/api-docs",
               "/graphql?query=%7B__schema%7Btypes%7Bname%7D%7D%7D", "/wp-admin/install.php", "/backup.zip"]
# probe path -> severity when it answers 200 with real content
PROBE_SEVERITY = {"/.env": "critical", "/.git/config": "critical", "/actuator/env": "critical",
                  "/actuator/heapdump": "critical", "/backup.zip": "critical", "/phpinfo.php": "major",
                  "/server-status": "major", "/debug": "major", "/__debug__/": "major", "/config.json": "minor",
                  "/.DS_Store": "minor", "/swagger-ui/": "info", "/v3/api-docs": "info",
                  "/graphql?query=%7B__schema%7Btypes%7Bname%7D%7D%7D": "minor", "/wp-admin/install.php": "major"}
SEV_RANK = {"blocker": 5, "critical": 4, "major": 3, "minor": 2, "trivial": 1, "info": 0}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def fetch(url, method="GET", headers=None, read=4096):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, **(headers or {})})
    try:
        r = OPENER.open(req, timeout=15)
    except urllib.error.HTTPError as e:  # 3xx/4xx/5xx still carry headers
        r = e
    body = r.read(read) if read else b""
    return r.status if hasattr(r, "status") else r.code, r.headers, body


def finding(out, sev, check, msg, url):
    out.append({"severity": sev, "check": check, "message": msg, "url": url})


def check_headers(url, h, out):
    https = url.startswith("https://")
    g = lambda k: h.get(k)
    if https:
        hsts = g("Strict-Transport-Security")
        if not hsts:
            finding(out, "major", "hsts", "Strict-Transport-Security missing", url)
        else:
            try:
                age = int([p.split("=")[1] for p in hsts.split(";") if p.strip().lower().startswith("max-age")][0])
                if age < 15552000:
                    finding(out, "minor", "hsts", f"HSTS max-age {age} < 180 days", url)
            except (IndexError, ValueError):
                finding(out, "minor", "hsts", f"HSTS without a valid max-age: {hsts}", url)
    csp = g("Content-Security-Policy")
    if not csp:
        finding(out, "major" if not g("Content-Security-Policy-Report-Only") else "minor", "csp",
                "Content-Security-Policy missing" + (" (only Report-Only set)" if g("Content-Security-Policy-Report-Only") else ""), url)
    elif "unsafe-inline" in csp and "script-src" in csp or ("default-src" in csp and "*" in csp.split("default-src")[1].split(";")[0]):
        finding(out, "minor", "csp", f"weak CSP: {csp[:120]}", url)
    if (g("X-Content-Type-Options") or "").lower() != "nosniff":
        finding(out, "minor", "nosniff", "X-Content-Type-Options: nosniff missing", url)
    if not g("X-Frame-Options") and "frame-ancestors" not in (csp or ""):
        finding(out, "minor", "clickjacking", "no X-Frame-Options and no CSP frame-ancestors (page can be framed)", url)
    if not g("Referrer-Policy"):
        finding(out, "trivial", "referrer-policy", "Referrer-Policy missing (browser default applies)", url)
    if not g("Permissions-Policy"):
        finding(out, "info", "permissions-policy", "Permissions-Policy missing", url)
    for k in ("Server", "X-Powered-By", "X-AspNet-Version", "X-AspNetMvc-Version"):
        v = g(k)
        if v and any(c.isdigit() for c in v):
            finding(out, "minor", "version-leak", f"{k} reveals a version: {v}", url)
        elif v and k != "Server":
            finding(out, "trivial", "version-leak", f"{k} reveals the stack: {v}", url)


def check_cookies(url, h, out):
    https = url.startswith("https://")
    for c in h.get_all("Set-Cookie") or []:
        name = c.split("=", 1)[0].strip()
        attrs = [p.strip().lower() for p in c.split(";")[1:]]
        flags = {p.split("=")[0] for p in attrs}
        sessionish = any(s in name.lower() for s in ("sess", "sid", "auth", "token", "jwt", "remember"))
        sev = "major" if sessionish else "minor"
        if https and "secure" not in flags:
            finding(out, sev, "cookie", f"cookie '{name}' without Secure", url)
        if "httponly" not in flags:
            finding(out, sev if sessionish else "info", "cookie", f"cookie '{name}' without HttpOnly", url)
        if "samesite" not in flags:
            finding(out, "minor", "cookie", f"cookie '{name}' without SameSite", url)
        elif "samesite=none" in attrs and "secure" not in flags:
            finding(out, "major", "cookie", f"cookie '{name}' SameSite=None without Secure", url)


def check_cors(url, origin, out):
    try:
        _, h, _ = fetch(url, headers={"Origin": origin}, read=0)
        _, ph, _ = fetch(url, method="OPTIONS", read=0,
                         headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
    except (urllib.error.URLError, OSError):
        return
    for hh, kind in ((h, "GET"), (ph, "preflight")):
        acao, acac = hh.get("Access-Control-Allow-Origin"), (hh.get("Access-Control-Allow-Credentials") or "").lower()
        if acao == origin and acac == "true":
            finding(out, "critical", "cors", f"{kind}: reflects arbitrary Origin {origin} with credentials", url)
            return
        if acao == origin:
            finding(out, "minor", "cors", f"{kind}: reflects arbitrary Origin {origin} (no credentials)", url)
            return
        if acao == "*" and acac == "true":
            finding(out, "major", "cors", f"{kind}: Allow-Origin * with Allow-Credentials true", url)
            return


def check_https_redirect(url, out):
    p = urllib.parse.urlparse(url)
    if p.scheme != "https":
        finding(out, "major" if p.hostname not in ("localhost", "127.0.0.1") else "info", "https",
                "site served over plain HTTP", url)
        return
    http_url = urllib.parse.urlunparse(p._replace(scheme="http", netloc=p.hostname))
    try:
        status, h, _ = fetch(http_url, read=0)
    except (urllib.error.URLError, OSError):
        return  # port 80 closed: nothing served over HTTP
    loc = h.get("Location") or ""
    if not (300 <= status < 400 and loc.startswith("https://")):
        finding(out, "major", "https", f"HTTP is not redirected to HTTPS ({http_url} -> {status} {loc})", url)


def check_tls(url, out):
    p = urllib.parse.urlparse(url)
    if p.scheme != "https":
        return {}
    host, port = p.hostname, p.port or 443
    info = {}
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=10) as s, ctx.wrap_socket(s, server_hostname=host) as t:
        cert = t.getpeercert()
        info["protocol"] = t.version()
        exp = dt.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.timezone.utc)
        days = (exp - dt.datetime.now(dt.timezone.utc)).days
        info["cert_expires"] = exp.date().isoformat()
        info["cert_days_left"] = days
        if days < 14:
            finding(out, "critical" if days < 0 else "major", "tls", f"certificate expires in {days} days", url)
        elif days < 30:
            finding(out, "minor", "tls", f"certificate expires in {days} days", url)
    for name, ver in (("TLSv1", ssl.TLSVersion.TLSv1), ("TLSv1.1", ssl.TLSVersion.TLSv1_1)):
        c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        c.check_hostname, c.verify_mode = False, ssl.CERT_NONE
        try:
            c.minimum_version = c.maximum_version = ver
            c.set_ciphers("ALL:@SECLEVEL=0")
            with socket.create_connection((host, port), timeout=10) as s, c.wrap_socket(s, server_hostname=host):
                finding(out, "major", "tls", f"server accepts {name}", url)
        except (ssl.SSLError, ValueError, OSError):
            info.setdefault("legacy_rejected_or_untestable", []).append(name)
    return info


def probe(base, out):
    """GET well-known sensitive paths on an origin; a random path is fetched first so SPA catch-all pages are ignored."""
    base = base.rstrip("/")
    try:
        s404, _, b404 = fetch(f"{base}/{uuid.uuid4().hex}")
    except (urllib.error.URLError, OSError):
        return []
    hits = []
    for path in PROBE_PATHS:
        try:
            st, h, body = fetch(base + path)
        except (urllib.error.URLError, OSError):
            continue
        if st == 200 and body and body != b404:
            hits.append({"path": path, "status": st, "type": h.get("Content-Type"), "bytes_read": len(body)})
            finding(out, PROBE_SEVERITY.get(path, "minor"), "exposed-path",
                    f"{path} answers 200 ({h.get('Content-Type')}); content not stored", base + path)
    return hits


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__.split("\n\n", 1)[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("urls", nargs="+")
    p.add_argument("--probe", action="store_true", help="also check well-known debug/secret paths")
    p.add_argument("--origin", default="https://evil.example", help="foreign Origin for the CORS check")
    p.add_argument("--json", help="write the full result as JSON")
    a = p.parse_args()

    findings, pages, errors = [], [], []
    for url in a.urls:
        if not url.startswith(("http://", "https://")):
            print(f"header_check: not an http(s) URL: {url}", file=sys.stderr)
            return 2
        try:
            status, h, _ = fetch(url, read=0)
        except (urllib.error.URLError, OSError) as e:
            errors.append({"url": url, "error": str(e)})
            continue
        before = len(findings)
        check_headers(url, h, findings)
        check_cookies(url, h, findings)
        check_cors(url, a.origin, findings)
        check_https_redirect(url, findings)
        try:
            tls = check_tls(url, findings)
        except (ssl.SSLError, OSError) as e:
            tls = {"error": str(e)}
            finding(findings, "major", "tls", f"TLS handshake failed: {e}", url)
        pages.append({"url": url, "status": status, "tls": tls, "findings": len(findings) - before,
                      "headers": {k: v for k, v in h.items() if k.lower() != "set-cookie"}})
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(a.urls[0]))
    probes = probe(origin, findings) if a.probe and pages else []

    findings.sort(key=lambda f: -SEV_RANK[f["severity"]])
    print("| Severity | Check | Finding | URL |\n|---|---|---|---|")
    for f in findings:
        print(f"| {f['severity']} | {f['check']} | {f['message']} | {f['url']} |")
    for e in errors:
        print(f"header_check: cannot reach {e['url']}: {e['error']}", file=sys.stderr)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"pages": pages, "findings": findings, "probes": probes, "errors": errors}, fh, indent=2)
    if errors and not pages:
        return 2
    return 1 if any(SEV_RANK[f["severity"]] >= 3 for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
