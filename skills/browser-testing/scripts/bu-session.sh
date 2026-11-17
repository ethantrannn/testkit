#!/usr/bin/env bash
# Isolated browser-use sessions for testkit streams.
#
#   bu-session.sh run <name> <<'PY'      run browser-use Python in session <name> (starts it if needed)
#   new_tab("https://staging.example.com/login"); wait_for_load(); print(page_info())
#   PY
#   bu-session.sh start <name>           start the session explicitly
#   bu-session.sh stop <name>            stop the session and delete its temporary profile
#   bu-session.sh stop-all               stop every session of this project
#   bu-session.sh status
#
# Mode (env TESTKIT_BU_MODE, else `browser.mode` in qa/config.yml, else isolated):
#   isolated  own headless Chrome per session (temp profile, own CDP port). Free, parallel-safe. Default.
#   cloud     Browser Use Cloud browser per session. Needs `browser-use login` or BROWSER_USE_API_KEY. Billed.
#   local     the user's running Chrome with their logins. One session at a time; never run streams in parallel.
#
# Other env: TESTKIT_CHROME (browser binary), TESTKIT_HEADED=1 (show the window),
#            TESTKIT_BU_TELEMETRY=1 (allow browser-use telemetry; off by default).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { echo "bu-session: $*" >&2; exit 1; }
command -v browser-use >/dev/null 2>&1 || die "browser-use not found. Install: uv tool install browser-use (or run: testkit doctor)"

# Project root = nearest folder with qa/config.yml; state lives in qa/.browser-use (git-ignored).
find_project() {
  local d="$PWD"
  while [ "$d" != "/" ] && [ -n "$d" ]; do
    [ -f "$d/qa/config.yml" ] && { echo "$d"; return; }
    d="$(dirname "$d")"
  done
}
PROJECT="$(find_project || true)"
if [ -n "$PROJECT" ]; then STATE="$PROJECT/qa/.browser-use"; else STATE="${TMPDIR:-/tmp}/testkit-browser-use"; fi
SESSIONS="$STATE/sessions"
mkdir -p "$SESSIONS"

# Read a key from the `browser:` block of qa/config.yml (flat keys only).
cfg() {
  [ -n "$PROJECT" ] || return 0
  awk -v k="$1" '
    /^[^[:space:]#]/ { inb = ($1 == "browser:") ; next }
    inb && $1 == k":" { v = $2; sub(/#.*/, "", v); gsub(/["'\'']/, "", v); print v; exit }
  ' "$PROJECT/qa/config.yml"
}

MODE="${TESTKIT_BU_MODE:-$(cfg mode)}"; MODE="${MODE:-isolated}"
case "$MODE" in isolated|cloud|local) ;; *) die "unknown mode '$MODE' (isolated|cloud|local)";; esac
HEADED="${TESTKIT_HEADED:-$(cfg headed)}"

export BH_AGENT_WORKSPACE="$STATE/workspace" BH_TAB_MARKER=0 BROWSER_USE_NO_UPDATE_CHECK=1 BH_OPEN_LIVE_URL=0
mkdir -p "$BH_AGENT_WORKSPACE"
# browser-use keeps a Unix socket under ~/.config; long home paths overflow the ~103-byte socket limit.
if [ -z "${BH_RUNTIME_DIR:-}" ] && [ "${#HOME}" -gt 40 ] && [ -d /tmp ]; then
  export BH_RUNTIME_DIR="/tmp/tk-$(id -u 2>/dev/null || echo 0)"
  mkdir -p "$BH_RUNTIME_DIR" && chmod 700 "$BH_RUNTIME_DIR"
fi
cp "$SCRIPT_DIR/agent_helpers.py" "$BH_AGENT_WORKSPACE/agent_helpers.py"
if [ "${TESTKIT_BU_TELEMETRY:-$(cfg telemetry)}" != "1" ] && [ "${TESTKIT_BU_TELEMETRY:-$(cfg telemetry)}" != "true" ]; then
  export ANONYMIZED_TELEMETRY=false
fi

safe_name() { printf '%s' "$1" | tr -c 'A-Za-z0-9-' '-' | cut -c1-40; }

find_chrome() {
  local c
  for c in "${TESTKIT_CHROME:-}" "$(cfg chrome_path)"; do [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return; }; done
  for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
           "/Applications/Chromium.app/Contents/MacOS/Chromium" \
           "$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do
    [ -x "$c" ] && { echo "$c"; return; }
  done
  for c in google-chrome google-chrome-stable chromium chromium-browser chrome; do
    command -v "$c" >/dev/null 2>&1 && { command -v "$c"; return; }
  done
  if command -v cygpath >/dev/null 2>&1; then  # Git Bash on Windows
    for c in "${PROGRAMFILES:-}" "${PROGRAMW6432:-}" "${LOCALAPPDATA:-}"; do
      [ -n "$c" ] || continue
      c="$(cygpath -u "$c")/Google/Chrome/Application/chrome.exe"
      [ -f "$c" ] && { echo "$c"; return; }
    done
  fi
  return 1
}

# Chrome on Windows needs a Windows path even when started from Git Bash.
native_path() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

free_port() {
  local p=$(( 9400 + $(printf '%s' "$1" | cksum | cut -d' ' -f1) % 500 )) i
  for i in $(seq 0 100); do port_in_use "$p" || { echo "$p"; return; }; p=$((p + 1)); done
  die "no free port for $1"
}

load() { # load <name> → sets PORT PID PROFILE SMODE, returns 1 when no state
  local f="$SESSIONS/$1.env"; [ -f "$f" ] || return 1
  PORT="" PID="" PROFILE="" SMODE=""
  # shellcheck disable=SC1090
  . "$f"
}

alive() { # alive <name>
  load "$1" || return 1
  case "$SMODE" in
    isolated) curl -fs "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1 ;;
    *) return 0 ;;
  esac
}

bu() { # bu <name> [browser-use args...] — run browser-use bound to the session
  local n="$1"; shift
  load "$n" || die "session $n is not started"
  case "$SMODE" in
    isolated) BU_NAME="tk-$n" BU_CDP_URL="http://127.0.0.1:$PORT" browser-use "$@" ;;
    cloud|local) BU_NAME="tk-$n" browser-use "$@" ;;
  esac
}

cmd_start() {
  local n; n="$(safe_name "$1")"
  if alive "$n"; then echo "session $n already running ($SMODE)"; return; fi
  rm -f "$SESSIONS/$n.env"
  case "$MODE" in
    isolated)
      local chrome port profile pid
      chrome="$(find_chrome)" || die "Chrome/Chromium not found. Install Chrome or set TESTKIT_CHROME / browser.chrome_path."
      port="$(free_port "$n")"
      profile="$(mktemp -d "${TMPDIR:-/tmp}/testkit-chrome-$n.XXXXXX")"
      local flags=(--remote-debugging-port="$port" --user-data-dir="$(native_path "$profile")" --no-first-run
                   --no-default-browser-check --disable-search-engine-choice-screen --window-size=1280,720)
      [ "$HEADED" = "1" ] || [ "$HEADED" = "true" ] || flags+=(--headless=new)
      [ "$(id -u 2>/dev/null || echo 1)" = "0" ] && flags+=(--no-sandbox)
      if command -v nohup >/dev/null 2>&1; then nohup "$chrome" "${flags[@]}" about:blank >"$profile.log" 2>&1 &
      else "$chrome" "${flags[@]}" about:blank >"$profile.log" 2>&1 & fi
      pid=$!
      local ok=0 i
      for i in $(seq 1 75); do curl -fs "http://127.0.0.1:$port/json/version" >/dev/null 2>&1 && { ok=1; break; }; sleep 0.2; done
      [ "$ok" = 1 ] || { kill "$pid" 2>/dev/null || true; die "Chrome did not open its debug port; see $profile.log"; }
      printf 'SMODE=isolated\nPORT=%s\nPID=%s\nPROFILE=%q\n' "$port" "$pid" "$profile" > "$SESSIONS/$n.env"
      echo "session $n started (isolated Chrome, port $port)"
      ;;
    cloud)
      printf 'SMODE=cloud\n' > "$SESSIONS/$n.env"
      browser-use <<PY || { rm -f "$SESSIONS/$n.env"; die "could not start a cloud browser (browser-use login, or set BROWSER_USE_API_KEY)"; }
r = start_remote_daemon("tk-$n")
print("session $n started (Browser Use Cloud)")
print("live view:", (r or {}).get("liveUrl") if isinstance(r, dict) else r)
PY
      ;;
    local)
      local f
      for f in "$SESSIONS"/*.env; do
        [ -e "$f" ] || continue
        grep -q '^SMODE=local' "$f" && die "a local-Chrome session is already active ($(basename "$f" .env)); local mode allows one at a time"
      done
      printf 'SMODE=local\n' > "$SESSIONS/$n.env"
      echo "session $n uses your running Chrome (local mode)"
      ;;
  esac
}

cmd_run() {
  local n; n="$(safe_name "$1")"
  alive "$n" || cmd_start "$n" >&2
  bu "$n"
}

cmd_stop() {
  local n; n="$(safe_name "$1")"
  load "$n" || { echo "session $n not running"; return; }
  case "$SMODE" in
    isolated)
      # Close Chrome through CDP first (works on every OS), then stop the daemon; kill is the fallback.
      printf 'cdp("Browser.close")\n' | bu "$n" >/dev/null 2>&1 || true
      bu "$n" --reload >/dev/null 2>&1 || true
      kill "$PID" 2>/dev/null || true
      for _ in $(seq 1 25); do curl -fs "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1 || break; sleep 0.2; done
      [ -n "$PROFILE" ] && rm -rf "$PROFILE" "$PROFILE.log"
      ;;
    cloud)
      browser-use <<PY >/dev/null 2>&1 || echo "warning: could not stop cloud browser tk-$n; stop it in the Browser Use dashboard" >&2
stop_remote_daemon("tk-$n")
PY
      ;;
    local) bu "$n" --reload >/dev/null 2>&1 || true ;;
  esac
  rm -f "$SESSIONS/$n.env"
  echo "session $n stopped"
}

cmd_status() {
  local f n any=0
  echo "mode: $MODE  state: $STATE"
  for f in "$SESSIONS"/*.env; do
    [ -e "$f" ] || continue; any=1; n="$(basename "$f" .env)"
    if alive "$n"; then echo "  $n  $SMODE  running${PORT:+  port $PORT}"; else echo "  $n  $SMODE  dead (run: stop $n)"; fi
  done
  [ "$any" = 1 ] || echo "  no sessions"
}

case "${1:-}" in
  run)      [ -n "${2:-}" ] || die "usage: run <name>"; cmd_run "$2" ;;
  start)    [ -n "${2:-}" ] || die "usage: start <name>"; cmd_start "$2" ;;
  stop)     [ -n "${2:-}" ] || die "usage: stop <name>"; cmd_stop "$2" ;;
  stop-all) for f in "$SESSIONS"/*.env; do [ -e "$f" ] && cmd_stop "$(basename "$f" .env)"; done; true ;;
  status)   cmd_status ;;
  *) sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
