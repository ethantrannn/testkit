#!/usr/bin/env bash
# Run the Maestro flows of one testkit stream and turn the output into evidence + result rows.
#
#   maestro_run.sh <RUN_ID> <STREAM_ID> [--device <id>] [--platform android|ios|web] [--only <TC_ID>]
#                  [--check-only] [-- <extra maestro test args>]
#
#   flows     qa/runs/<RUN_ID>/mobile/<STREAM_ID>/*.yaml   (sub-flows in _shared/ are not run directly)
#   junit     qa/runs/<RUN_ID>/results/<STREAM_ID>-maestro.xml
#   artifacts qa/runs/<RUN_ID>/evidence/<STREAM_ID>/maestro/  (logs, commands, screenshots; secrets redacted)
#   evidence  qa/runs/<RUN_ID>/evidence/<STREAM_ID>/<name>.png  (copied takeScreenshot + <TC_ID>-fail.png)
#
# Test accounts reach the flows as MAESTRO_* environment variables (Maestro reads them automatically,
# e.g. ${MAESTRO_MEMBER_EMAIL}); export them before calling, never pass secrets with -e.
# --only reruns one case (<TC_ID>.yaml). --check-only validates every flow with `maestro check-syntax` and stops.
# Exit: 0 all flows passed, 1 a flow failed, 2 setup error (Maestro/Java/device/flows missing).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
die() { echo "maestro_run: $*" >&2; exit 2; }
usage() { sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2; }

[ $# -ge 2 ] || usage
RUN_ID="$1"; STREAM="$2"; shift 2
DEVICE=""; PLATFORM=""; ONLY=""; CHECK_ONLY=0; EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --device) DEVICE="${2:-}"; shift 2 ;;
    --platform) PLATFORM="${2:-}"; shift 2 ;;
    --only) ONLY="${2:-}"; shift 2 ;;
    --check-only) CHECK_ONLY=1; shift ;;
    --) shift; EXTRA=("$@"); break ;;
    -h|--help) usage ;;
    *) die "unknown option $1 (see --help)" ;;
  esac
done

[ -f qa/config.yml ] || die "run from the project root (qa/config.yml not found)"
FLOWS="qa/runs/$RUN_ID/mobile/$STREAM"
[ -d "$FLOWS" ] || die "no flows folder $FLOWS"

# Maestro: PATH, else the default install location of the official installer.
MAESTRO="$(command -v maestro 2>/dev/null || true)"
[ -n "$MAESTRO" ] || { [ -x "$HOME/.maestro/bin/maestro" ] && MAESTRO="$HOME/.maestro/bin/maestro"; } || true
[ -n "$MAESTRO" ] || die "maestro not found. Install: curl -fsSL https://get.maestro.mobile.dev | bash  (or: testkit doctor)"
export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true

# Maestro 2.x needs Java 17+.
JV="$("${JAVA_HOME:+$JAVA_HOME/bin/}java" -version 2>&1 | awk -F'"' '/version/ {print $2; exit}')"
case "$JV" in
  1.*|9*|1[0-6]*|"") die "Java 17+ required (found '${JV:-none}'). Install a JDK 17/21 and set JAVA_HOME." ;;
esac

# 1. Syntax check every flow (fails fast, no device needed).
n=0; bad=0
for f in "$FLOWS"/*.yaml "$FLOWS"/*.yml; do
  [ -e "$f" ] || continue
  n=$((n + 1))
  if ! out="$("$MAESTRO" check-syntax "$f" 2>&1)"; then
    bad=$((bad + 1)); echo "SYNTAX  $f: $(printf '%s' "$out" | tr '\n' ' ')" >&2
  fi
done
[ "$n" -gt 0 ] || die "no *.yaml flows in $FLOWS"
[ "$bad" -eq 0 ] || die "$bad of $n flow(s) have syntax errors"
echo "syntax OK: $n flow(s)"
[ "$CHECK_ONLY" = 1 ] && exit 0

# 2. Run.
RESULTS="qa/runs/$RUN_ID/results"; EVID="qa/runs/$RUN_ID/evidence/$STREAM"; ART="$EVID/maestro"
REPORT="$RESULTS/$STREAM-maestro"; [ -n "$ONLY" ] && REPORT="$RESULTS/$STREAM-$ONLY-maestro"   # a rerun keeps the stream report
mkdir -p "$RESULTS" "$ART"   # maestro does not create the --output folder
ARGS=()
[ -n "$DEVICE" ] && ARGS+=(--device "$DEVICE")
[ -n "$PLATFORM" ] && ARGS+=(--platform "$PLATFORM")
rc=0
TARGET="$FLOWS"
if [ -n "$ONLY" ]; then TARGET="$FLOWS/$ONLY.yaml"; [ -f "$TARGET" ] || die "no flow $TARGET"; fi
"$MAESTRO" "${ARGS[@]+"${ARGS[@]}"}" test "$TARGET" --format junit --output "$REPORT.xml" \
  --test-output-dir "$ART" --test-suite-name "$RUN_ID-$STREAM" "${EXTRA[@]+"${EXTRA[@]}"}" || rc=$?
[ -f "$REPORT.xml" ] || die "maestro produced no report (exit $rc). Device connected? Try: maestro list-devices"

# 3. Redact secrets, copy screenshots, print result rows.
PY="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)" || die "python3 not found"
"$PY" "$SCRIPT_DIR/maestro_report.py" --junit "$REPORT.xml" --artifacts "$ART" --evidence "$EVID" \
  --json "$REPORT.json" || true
exit $(( rc == 0 ? 0 : 1 ))
