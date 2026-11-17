#!/usr/bin/env bash
# testkit installer — macOS / Linux.
#
#   curl -fsSL __TESTKIT_BASE_URL__/install.sh | bash
#   curl -fsSL __TESTKIT_BASE_URL__/install.sh | bash -s -- --yes
#
# Checks for a coding agent (installs Claude Code if none), installs uv + the browser-use CLI, pandoc,
# checks for Chrome (asking before each install),
# downloads the kit to ~/.testkit/kit and puts the `testkit` command in ~/.local/bin.
# Then, in any project folder:  testkit init
#
# Options / env:
#   --yes            | TESTKIT_YES=1            accept every install prompt
#   --skip-prereqs   | TESTKIT_SKIP_PREREQS=1   only install the testkit command
#   --with LIST      | TESTKIT_WITH=LIST        optional tool groups, comma separated, or "all":
#       api (Hurl) · mail (Mailpit) · db (psql + mysql clients) · automation (Node.js for Playwright)
#       video (ffmpeg) · load (k6) · mobile (Maestro) · security (checks Docker for OWASP ZAP)
#       knowledge (Graphiti knowledge graph in Docker) · office (LibreOffice + poppler) · agent-browser (Node.js + agent-browser)
#   --with-office / --with-agent-browser          same as --with office / --with agent-browser
#   --source <src>   | TESTKIT_SOURCE           site URL, GitHub owner/repo, git URL (.git) or local folder
#   --ref <ref>      | TESTKIT_REF              branch or tag (default: main)

set -euo pipefail

DEFAULT_SOURCE="__TESTKIT_BASE_URL__"   # replaced by scripts/build-site.sh with the site URL
NODE_MIN_MAJOR=22
NVM_VERSION="v0.40.3"
MAESTRO_VERSION="2.12.0"
TESTKIT_HOME="${TESTKIT_HOME:-$HOME/.testkit}"
BIN_DIR="$HOME/.local/bin"

YES="${TESTKIT_YES:-0}"
SKIP_PREREQS="${TESTKIT_SKIP_PREREQS:-0}"
WITH_AB="${TESTKIT_AGENT_BROWSER:-0}"
WITH_OFFICE="${TESTKIT_OFFICE:-0}"
WITH="${TESTKIT_WITH:-}"
EXTRAS="api mail db automation video load mobile security knowledge office agent-browser"
SOURCE="${TESTKIT_SOURCE:-}"
REF="${TESTKIT_REF:-main}"

if [ -t 1 ]; then B=$'\033[1m' G=$'\033[32m' Y=$'\033[33m' R=$'\033[31m' N=$'\033[0m'; else B="" G="" Y="" R="" N=""; fi
step() { printf '\n%s==> %s%s\n' "$B" "$*" "$N"; }
ok()   { printf '  %s✔%s %s\n' "$G" "$N" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$*"; }
die()  { printf '  %s✘%s %s\n' "$R" "$N" "$*" >&2; exit 1; }
has()  { command -v "$1" >/dev/null 2>&1; }

# When piped into bash, stdin is the script itself, so prompts read from the terminal.
confirm() {
  [ "$YES" = 1 ] && return 0
  if [ -r /dev/tty ] && { exec 3</dev/tty; } 2>/dev/null; then
    local a; printf '  ? %s [y/N] ' "$1" > /dev/tty; read -r a <&3 || a=""; exec 3<&-
    [[ "$a" =~ ^[Yy]$ ]]
  else
    warn "No terminal: skipping '$1' (use --yes to allow)"; return 1
  fi
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      -y|--yes) YES=1 ;;
      --skip-prereqs) SKIP_PREREQS=1 ;;
      --with-agent-browser) WITH_AB=1 ;;
      --with-office) WITH_OFFICE=1 ;;
      --with) WITH="${WITH:+$WITH,}${2:?--with needs a list}"; shift ;;
      --with=*) WITH="${WITH:+$WITH,}${1#--with=}" ;;
      --source) SOURCE="${2:?}"; shift ;;
      --ref) REF="${2:?}"; shift ;;
      -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
      *) die "Unknown option: $1" ;;
    esac; shift
  done

  case "$(uname -s)" in Darwin) PLATFORM=macos ;; Linux) PLATFORM=linux ;; *) die "Unsupported OS. On Windows use install.ps1." ;; esac
  [ "$WITH" = all ] && WITH="${EXTRAS// /,}"
  local x
  for x in ${WITH//,/ }; do
    case " $EXTRAS " in *" $x "*) ;; *) die "Unknown --with item: $x (choose from: ${EXTRAS// /, }, all)" ;; esac
    [ "$x" = office ] && WITH_OFFICE=1
    [ "$x" = agent-browser ] && WITH_AB=1
  done

  # Run from a local checkout (./install.sh) → install that checkout.
  if [ -z "$SOURCE" ]; then
    local here=""
    [ -f "${BASH_SOURCE[0]:-}" ] && here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -n "$here" ] && [ -f "$here/.claude-plugin/plugin.json" ] && [ -f "$here/bin/testkit" ]; then SOURCE="$here"
    else SOURCE="$DEFAULT_SOURCE"; fi
  fi
  [[ "$SOURCE" == __*__ ]] && die "This copy of install.sh was not built for a site. Use the published URL, or pass --source."

  printf '%stestkit installer%s (%s) — source: %s@%s\n' "$B" "$N" "$PLATFORM" "$SOURCE" "$REF"

  if [ "$SKIP_PREREQS" = 1 ]; then warn "skipping prerequisites"
  else
    ensure_claude; ensure_browser_use; check_chrome; ensure_docs_tools
    if [ "$WITH_AB" = 1 ]; then ensure_node; ensure_agent_browser; fi
    ensure_extras
  fi

  install_cli
  want knowledge && setup_graph

  step "Done"
  cat <<EOF
  Open a project folder and run:
    testkit init
  Then start Claude Code there and run /testkit-config.
  Check your setup any time with: testkit doctor
EOF
  [ "${PATH_CHANGED:-0}" = 1 ] && warn "Open a new terminal (or run: export PATH=\"$BIN_DIR:\$PATH\") so 'testkit' is on PATH."
  return 0
}

ensure_node() {
  step "Node.js >= $NODE_MIN_MAJOR (for agent-browser)"
  if has node && [ "$(node -p 'process.versions.node.split(".")[0]')" -ge "$NODE_MIN_MAJOR" ]; then ok "node $(node -v)"; return; fi
  if has node; then warn "node $(node -v) is too old"; else warn "node not found"; fi
  if [ "$PLATFORM" = macos ] && has brew; then
    confirm "Install Node.js with Homebrew?" || die "Node.js >= $NODE_MIN_MAJOR is required"
    brew install node
  else
    confirm "Install Node.js 22 with nvm $NVM_VERSION (user-local, no sudo)?" || die "Node.js >= $NODE_MIN_MAJOR is required"
    export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
    [ -s "$NVM_DIR/nvm.sh" ] || curl -fsSL "https://raw.githubusercontent.com/nvm-sh/nvm/$NVM_VERSION/install.sh" | bash
    # shellcheck disable=SC1091
    . "$NVM_DIR/nvm.sh"; nvm install 22; nvm alias default 22; nvm use 22
  fi
  ok "node $(node -v)"
}

ensure_claude() {
  step "Coding agent (Claude Code, Codex, Cursor, Gemini CLI or Copilot)"
  local a found=0
  for a in claude codex cursor-agent gemini copilot; do
    has "$a" && { ok "$a $("$a" --version 2>/dev/null | head -1)"; found=1; }
  done
  [ -d "/Applications/Cursor.app" ] && { ok "Cursor app"; found=1; }
  [ "$found" = 1 ] && return
  confirm "No coding agent found. Install Claude Code with the official installer?" || die "testkit needs a coding agent (Claude Code, Codex, Cursor, Gemini CLI or Copilot)"
  curl -fsSL https://claude.ai/install.sh | bash
  export PATH="$BIN_DIR:$PATH"
  has claude || die "Claude Code installed but not on PATH. Open a new terminal and re-run."
  ok "claude $(claude --version | head -1)"
}

ensure_browser_use() {
  step "uv + browser-use CLI"
  if ! has uv; then
    confirm "Install uv (Python tool manager, astral.sh)?" || die "uv is required to install browser-use"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$BIN_DIR:$PATH"
    has uv || die "uv installed but not on PATH. Open a new terminal and re-run."
  fi
  ok "uv $(uv --version | awk '{print $2}')"
  if has browser-use && browser-use --version 2>/dev/null | grep -qE '^browser-use [1-9]'; then
    ok "$(browser-use --version | head -1)"; return
  fi
  has browser-use && warn "browser-use $(browser-use --version 2>/dev/null | head -1) is too old (testkit needs 1.x)"
  confirm "Install the browser-use CLI (uv tool install browser-use)?" || die "browser-use is required"
  uv tool install --force --upgrade browser-use
  export PATH="$BIN_DIR:$PATH"; hash -r
  ok "$(browser-use --version | head -1)"
}

# Install OS packages with whatever package manager the machine has.
# Homebrew wins when present (macOS, and Linuxbrew); "-" means the distro has no package.
pkg_install() { # pkg_install <brew formula|cask:name> <apt name|-> <dnf name|-> [manual install hint]
  if has brew && { [ "$PLATFORM" = macos ] || [ "${1#cask:}" = "$1" ]; }; then
    case "$1" in cask:*) brew install --cask "${1#cask:}" ;; *) brew install "$1" ;; esac
  elif [ "$PLATFORM" = macos ]; then warn "Homebrew not found; ${4:-install $1 manually}"; return 1
  elif has apt-get && [ "$2" != - ]; then sudo apt-get install -y "$2"
  elif has dnf && [ "$3" != - ]; then sudo dnf install -y "$3"
  else warn "No package for this system; ${4:-install $1 manually}"; return 1; fi
}

# Java 17+ on PATH or in JAVA_HOME (Maestro needs it).
java_ok() {
  local j="java"; [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/java" ] && j="$JAVA_HOME/bin/java"
  command -v "$j" >/dev/null 2>&1 || return 1
  local v; v="$("$j" -version 2>&1 | head -1 | sed -E 's/.*version "([0-9]+)(\.([0-9]+))?.*/\1 \3/')"
  set -- $v; [ "$1" = 1 ] && v="${2:-0}" || v="$1"
  [ "${v:-0}" -ge 17 ] 2>/dev/null
}

want() { case ",$WITH," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }

# ensure_tool <group> <command> <label> <brew> <apt> <dnf> <hint>
ensure_tool() {
  if has "$2"; then ok "$3 ($(command -v "$2"))"; return; fi
  confirm "Install $3 (--with $1)?" || { warn "$3 skipped"; return; }
  pkg_install "$4" "$5" "$6" "$7" && hash -r && ok "$3 installed" || warn "$3 not installed; $7"
}

setup_graph() {
  step "Knowledge graph (Graphiti)"
  if ! has docker; then warn "Docker not found: install Docker, then run: testkit graph up"; return 0; fi
  if confirm "Start Graphiti now, or reuse one already running? (first start downloads a ~3.7 GB image, about 11 GB on disk; needs an LLM key such as OPENAI_API_KEY in your environment, or Ollama)"; then
    "$BIN_DIR/testkit" graph up || warn "Graphiti not started; fix the message above, then run: testkit graph up"
  else
    warn "skipped; run 'testkit graph up' later. testkit keeps knowledge in files until a graph is available"
  fi
  return 0
}

ensure_extras() {
  [ -n "$WITH" ] || return 0
  step "Optional tools: $WITH"
  want api        && ensure_tool api hurl "Hurl (API testing)" hurl - - "see https://hurl.dev/docs/installation.html (Ubuntu: ppa:lepapareil/hurl)"
  want mail       && ensure_tool mail mailpit "Mailpit (test inbox)" mailpit - - "run: sudo sh < <(curl -sL https://raw.githubusercontent.com/axllent/mailpit/develop/install.sh)"
  if want db; then
    ensure_tool db psql "psql (PostgreSQL client)" libpq postgresql-client postgresql "install a PostgreSQL client"
    ensure_tool db mysql "mysql client" mysql-client default-mysql-client mysql "install a MySQL/MariaDB client"
    [ "$PLATFORM" = macos ] && ! has psql && [ -d "$(brew --prefix 2>/dev/null)/opt/libpq/bin" ] && \
      warn "libpq is keg-only: add $(brew --prefix)/opt/libpq/bin to PATH (same for mysql-client)"
  fi
  want automation && { ensure_node; ok "Playwright is installed per project by the testkit-automate skill (run_suite.py --install)"; }
  want video      && ensure_tool video ffmpeg "ffmpeg (bug and guide videos)" ffmpeg ffmpeg ffmpeg "install ffmpeg (Fedora: RPM Fusion)"
  want load       && ensure_tool load k6 "k6 (load tests)" k6 - - "see https://grafana.com/docs/k6/latest/set-up/install-k6/"
  if want mobile; then
    if has maestro; then ok "Maestro ($(command -v maestro))"
    elif ! java_ok; then warn "Maestro needs Java 17+ (found: $(java -version 2>&1 | head -1 || echo none)). Install one (macOS: brew install openjdk@21; Linux: openjdk-17-jdk), set JAVA_HOME, then re-run with --with mobile"
    elif confirm "Install the Maestro CLI $MAESTRO_VERSION (get.maestro.mobile.dev)?"; then
      curl -fsSL "https://get.maestro.mobile.dev" | MAESTRO_VERSION="$MAESTRO_VERSION" bash && export PATH="$HOME/.maestro/bin:$PATH" && ok "Maestro installed (~/.maestro/bin)"
    fi
    warn "Mobile tests also need an Android emulator/iOS simulator or a device; testkit does not install SDKs"
  fi
  if want security; then
    if has docker; then ok "Docker (OWASP ZAP baseline runs as a container on demand)"
    else warn "Docker not found: needed only for the ZAP baseline scan (quality-audits). Install Docker Desktop or docker.io"; fi
  fi
  return 0
}

ensure_docs_tools() {
  step "Word documents (docx skill)"
  if has pandoc; then ok "pandoc $(pandoc --version | head -1 | awk '{print $2}')"
  elif confirm "Install pandoc (reads .docx specs)?"; then pkg_install pandoc pandoc pandoc && ok "pandoc installed"
  else warn "pandoc skipped; agents cannot read Word specs until it is installed"; fi
  if has soffice || [ -d "/Applications/LibreOffice.app" ]; then ok "LibreOffice"
  elif [ "$WITH_OFFICE" = 1 ] && confirm "Install LibreOffice (~700 MB, for rendering Word exports to check them)?"; then
    pkg_install cask:libreoffice libreoffice-writer libreoffice-writer
  else warn "LibreOffice not installed (optional: --with-office). Word exports are validated but not rendered."; fi
  if has pdftoppm; then ok "poppler (pdftoppm)"
  elif [ "$WITH_OFFICE" = 1 ]; then pkg_install poppler poppler-utils poppler-utils || true
  fi
  return 0
}

check_chrome() {
  step "Chrome"
  local c
  for c in "/Applications/Google Chrome.app" "/Applications/Chromium.app" "$HOME/Applications/Google Chrome.app"; do
    [ -d "$c" ] && { ok "$c"; return; }
  done
  for c in google-chrome google-chrome-stable chromium chromium-browser; do
    has "$c" && { ok "$(command -v "$c")"; return; }
  done
  warn "Chrome/Chromium not found. Install Google Chrome (testkit opens its own headless Chrome per test stream)."
  [ "$PLATFORM" = linux ] && warn "  Debian/Ubuntu: https://www.google.com/chrome/ (.deb), or: sudo apt install chromium"
  return 0
}

ensure_agent_browser() {
  step "agent-browser + Chromium"
  if has agent-browser; then ok "agent-browser $(agent-browser --version | awk '{print $NF}')"; return; fi
  confirm "Install agent-browser (npm -g) and its Chromium?" || { warn "skipped; testkit needs a browser tool to run tests"; return; }
  npm install -g agent-browser || die "npm install -g failed. With a system Node, try: npm config set prefix ~/.npm-global && export PATH=~/.npm-global/bin:\$PATH"
  hash -r
  if [ "$PLATFORM" = linux ] && confirm "Also install Chromium system libraries (sudo apt/dnf)?"; then
    agent-browser install --with-deps
  else
    agent-browser install
  fi
  ok "agent-browser $(agent-browser --version | awk '{print $NF}')"
}

install_cli() {
  step "testkit command"
  mkdir -p "$TESTKIT_HOME" "$BIN_DIR"
  printf 'source=%s\nref=%s\n' "$SOURCE" "$REF" > "$TESTKIT_HOME/config"

  # Download the kit to a temp folder, then swap it in.
  local tmp; tmp="$(mktemp -d "$TESTKIT_HOME/.fetch.XXXXXX")"; mkdir -p "$tmp/kit"
  if [ -d "$SOURCE" ]; then
    (cd "$SOURCE" && tar cf - --exclude .git --exclude node_modules --exclude 'skills/browser-testing/references' .) | (cd "$tmp/kit" && tar xf -)
  elif [[ "$SOURCE" == git@* || "$SOURCE" == *.git ]]; then
    git clone --quiet --depth 1 --branch "$REF" "$SOURCE" "$tmp/kit"; rm -rf "$tmp/kit/.git"
  elif [[ "$SOURCE" == http://* || "$SOURCE" == https://* ]]; then
    curl -fsSL "${SOURCE%/}/kit.tar.gz" | tar xz -C "$tmp/kit" --strip-components=1 \
      || die "Could not download ${SOURCE%/}/kit.tar.gz"
  else
    curl -fsSL "https://codeload.github.com/$SOURCE/tar.gz/$REF" | tar xz -C "$tmp/kit" --strip-components=1 \
      || die "Could not download https://github.com/$SOURCE ($REF)"
  fi
  [ -f "$tmp/kit/bin/testkit" ] || die "$SOURCE@$REF does not look like testkit (bin/testkit missing)"
  rm -rf "$TESTKIT_HOME/kit.old"; [ -d "$TESTKIT_HOME/kit" ] && mv "$TESTKIT_HOME/kit" "$TESTKIT_HOME/kit.old"
  mv "$tmp/kit" "$TESTKIT_HOME/kit"; rm -rf "$TESTKIT_HOME/kit.old" "$tmp"
  chmod +x "$TESTKIT_HOME/kit/bin/testkit"
  ln -sf "$TESTKIT_HOME/kit/bin/testkit" "$BIN_DIR/testkit"
  ok "$("$BIN_DIR/testkit" version) → $BIN_DIR/testkit"

  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
      local rc
      case "${SHELL:-}" in */zsh) rc="$HOME/.zshrc" ;; */bash) rc="$HOME/.bashrc"; [ "$PLATFORM" = macos ] && rc="$HOME/.bash_profile" ;; *) rc="$HOME/.profile" ;; esac
      local line="export PATH=\"\$HOME/.local/bin:\$PATH\""
      grep -qxF "$line" "$rc" 2>/dev/null || printf '\n# added by testkit installer\n%s\n' "$line" >> "$rc"
      ok "added ~/.local/bin to PATH in $rc"; PATH_CHANGED=1 ;;
  esac
}

main "$@"
