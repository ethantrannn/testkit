#!/usr/bin/env bash
# Build the static install site into public/:
#   install.sh, install.ps1   one-line installers with the site URL baked in
#   kit.tar.gz, kit.zip       the kit that `testkit init` downloads
#   version.txt, index.html
#
# Base URL: $TESTKIT_BASE_URL, else https://$VERCEL_PROJECT_PRODUCTION_URL (set by Vercel at build time).
#   TESTKIT_BASE_URL=https://testkit.example.com ./scripts/build-site.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/public"

BASE_URL="${TESTKIT_BASE_URL:-}"
[ -z "$BASE_URL" ] && [ -n "${VERCEL_PROJECT_PRODUCTION_URL:-}" ] && BASE_URL="https://$VERCEL_PROJECT_PRODUCTION_URL"
[ -n "$BASE_URL" ] || { echo "Set TESTKIT_BASE_URL (e.g. https://testkit.example.com)" >&2; exit 1; }
BASE_URL="${BASE_URL%/}"
VERSION="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$ROOT/.claude-plugin/plugin.json" | head -1)"

rm -rf "$OUT"; mkdir -p "$OUT/.stage/testkit"

# Kit contents: everything except build output, VCS, local state and generated references.
(cd "$ROOT" && tar cf - \
  --exclude ./.git --exclude ./public --exclude ./.vercel --exclude ./plans --exclude node_modules \
  --exclude ./skills/browser-testing/references --exclude .DS_Store --exclude '*.pyc' --exclude '__pycache__' .) | (cd "$OUT/.stage/testkit" && tar xf -)

tar czf "$OUT/kit.tar.gz" -C "$OUT/.stage" testkit
if command -v zip >/dev/null 2>&1; then (cd "$OUT/.stage" && zip -qrX "$OUT/kit.zip" testkit)
else (cd "$OUT/.stage" && python3 -m zipfile -c "$OUT/kit.zip" testkit); fi
rm -rf "$OUT/.stage"

sed "s#__TESTKIT_BASE_URL__#$BASE_URL#g" "$ROOT/install.sh"  > "$OUT/install.sh"
sed "s#__TESTKIT_BASE_URL__#$BASE_URL#g" "$ROOT/install.ps1" > "$OUT/install.ps1"
echo "$VERSION" > "$OUT/version.txt"

cat > "$OUT/index.html" <<EOF
<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>testkit</title>
<style>
  :root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--code:#f4f4f2}
  @media (prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--muted:#999;--code:#1e1e1e}}
  body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,sans-serif}
  main{max-width:720px;margin:0 auto;padding:48px 16px}
  pre{background:var(--code);padding:12px 16px;border-radius:8px;overflow-x:auto}
  small{color:var(--muted)}
</style></head>
<body><main>
<h1>testkit ${VERSION}</h1>
<p>QA agents cho Claude Code: lập kế hoạch, viết, review và chạy test case trên trình duyệt, tạo và verify bug.</p>
<h2>macOS / Linux</h2>
<pre>curl -fsSL ${BASE_URL}/install.sh | bash</pre>
<h2>Windows (PowerShell)</h2>
<pre>irm ${BASE_URL}/install.ps1 | iex</pre>
<h2>Trong thư mục dự án</h2>
<pre>testkit init</pre>
<small>Kiểm tra môi trường: <code>testkit doctor</code></small>
</main></body></html>
EOF

echo "Built $OUT for $BASE_URL (testkit $VERSION):"
ls -l "$OUT" | tail -n +2
