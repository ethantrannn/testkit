# testkit installer - Windows (PowerShell 5.1+ or 7+).
#
#   irm __TESTKIT_BASE_URL__/install.ps1 | iex
#
# Checks for a coding agent (installs Claude Code if none), installs uv + the browser-use CLI, pandoc,
# checks for Chrome (asking before each install),
# downloads the kit to %USERPROFILE%\.testkit\kit and adds the `testkit` command to your PATH.
# Then, in any project folder:  testkit init
#
# Env (set before running, e.g. $env:TESTKIT_YES = '1'):
#   TESTKIT_YES=1            accept every install prompt
#   TESTKIT_SKIP_PREREQS=1   only install the testkit command
#   TESTKIT_WITH=LIST        optional tool groups, comma separated, or "all":
#       api (Hurl) · mail (Mailpit) · db (psql) · automation (Node.js for Playwright) · video (ffmpeg)
#       load (k6) · mobile (Java 21; Maestro is a manual zip) · security (checks Docker for OWASP ZAP)
#       knowledge (Graphiti knowledge graph in Docker) · office (LibreOffice) · agent-browser (Node.js + agent-browser)
#   TESTKIT_OFFICE=1 / TESTKIT_AGENT_BROWSER=1  same as office / agent-browser in TESTKIT_WITH
#   TESTKIT_SOURCE           site URL, GitHub owner/repo, git URL (.git) or local folder
#   TESTKIT_REF              branch or tag (default: main)

& {
  $ErrorActionPreference = 'Stop'
  $DefaultSource = '__TESTKIT_BASE_URL__'   # replaced by scripts/build-site.sh with the site URL
  $NodeMinMajor = 22
  $TestkitHome = if ($env:TESTKIT_HOME) { $env:TESTKIT_HOME } else { Join-Path $HOME '.testkit' }
  $BinDir = Join-Path $TestkitHome 'bin'
  $Yes = $env:TESTKIT_YES -eq '1'
  $Ref = if ($env:TESTKIT_REF) { $env:TESTKIT_REF } else { 'main' }
  $Source = $env:TESTKIT_SOURCE
  if (-not $Source) {
    # Run from a local checkout (.\install.ps1) -> install that checkout.
    if ($PSCommandPath -and (Test-Path (Join-Path (Split-Path $PSCommandPath) 'bin/testkit.ps1'))) { $Source = Split-Path $PSCommandPath }
    else { $Source = $DefaultSource }
  }
  if ($Source -like '__*__') { throw 'This copy of install.ps1 was not built for a site. Use the published URL, or set TESTKIT_SOURCE.' }

  function Step($m) { Write-Host "`n==> $m" }
  function Ok($m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
  function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }
  function Die($m)  { Write-Host "  [x]  $m" -ForegroundColor Red; throw $m }
  function Has($c)  { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
  $Extras = @('api', 'mail', 'db', 'automation', 'video', 'load', 'mobile', 'security', 'knowledge', 'office', 'agent-browser')
  $With = @(($env:TESTKIT_WITH -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
  if ($With -contains 'all') { $With = $Extras }
  foreach ($w in $With) { if ($Extras -notcontains $w) { throw "Unknown TESTKIT_WITH item: $w (choose from: $($Extras -join ', '), all)" } }
  if ($With -contains 'office') { $env:TESTKIT_OFFICE = '1' }
  if ($With -contains 'agent-browser') { $env:TESTKIT_AGENT_BROWSER = '1' }
  function Confirm-Action($q) { if ($Yes) { return $true }; return (Read-Host "  ? $q [y/N]") -match '^[Yy]$' }
  function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') + ";$HOME\.local\bin;$env:APPDATA\npm"
  }
  function Invoke-Native {
    $exe, $rest = $args
    & $exe @rest | Out-Host
    if ($LASTEXITCODE -ne 0) { Die "$exe $($rest -join ' ') failed ($LASTEXITCODE)" }
  }

  Write-Host "testkit installer (windows) - source: $Source@$Ref"

  if ($env:TESTKIT_SKIP_PREREQS -eq '1') { Warn 'skipping prerequisites' }
  else {
    Step 'Coding agent (Claude Code, Codex, Cursor, Gemini CLI or Copilot)'
    $agentClis = @('claude', 'codex', 'cursor-agent', 'gemini', 'copilot') | Where-Object { Has $_ }
    foreach ($a in $agentClis) { Ok "$a $(& $a --version 2>$null | Select-Object -First 1)" }
    $cursorApp = Test-Path "$env:LOCALAPPDATA\Programs\cursor\Cursor.exe"
    if ($cursorApp) { Ok 'Cursor app' }
    if (-not $agentClis -and -not $cursorApp) {
      if (-not (Confirm-Action 'No coding agent found. Install Claude Code with the official installer?')) { Die 'testkit needs a coding agent (Claude Code, Codex, Cursor, Gemini CLI or Copilot)' }
      Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
      Update-SessionPath
      if (-not (Has claude)) { Die 'Claude Code installed but not on PATH. Open a new terminal and re-run.' }
      Ok "claude $(claude --version | Select-Object -First 1)"
    }

    Step 'uv + browser-use CLI'
    if (-not (Has uv)) {
      if (-not (Confirm-Action 'Install uv (Python tool manager, astral.sh)?')) { Die 'uv is required to install browser-use' }
      Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
      Update-SessionPath
      if (-not (Has uv)) { Die 'uv installed but not on PATH. Open a new terminal and re-run.' }
    }
    Ok "$(uv --version)"
    $buv = if (Has browser-use) { browser-use --version 2>$null | Select-Object -First 1 } else { '' }
    if ($buv -match '^browser-use [1-9]') { Ok $buv }
    else {
      if ($buv) { Warn "$buv is too old (testkit needs 1.x)" }
      if (-not (Confirm-Action 'Install the browser-use CLI (uv tool install browser-use)?')) { Die 'browser-use is required' }
      Invoke-Native uv tool install --force --upgrade browser-use
      Update-SessionPath
      Ok "$(browser-use --version | Select-Object -First 1)"
    }

    Step 'Chrome'
    $chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
                "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if ($chrome) { Ok $chrome }
    elseif ((Has winget) -and (Confirm-Action 'Chrome not found. Install Google Chrome with winget?')) {
      Invoke-Native winget install --id Google.Chrome -e --accept-source-agreements --accept-package-agreements
    } else { Warn 'Chrome not found. Install Google Chrome (testkit opens its own headless Chrome per test stream).' }

    Step 'Word documents (docx skill)'
    if (Has pandoc) { Ok "$(pandoc --version | Select-Object -First 1)" }
    elseif ((Has winget) -and (Confirm-Action 'Install pandoc (reads .docx specs)?')) {
      Invoke-Native winget install --id JohnMacFarlane.Pandoc -e --accept-source-agreements --accept-package-agreements
      Update-SessionPath
    } else { Warn 'pandoc skipped; agents cannot read Word specs until it is installed' }
    $soffice = @("$env:ProgramFiles\LibreOffice\program\soffice.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($soffice -or (Has soffice)) { Ok 'LibreOffice' }
    elseif ($env:TESTKIT_OFFICE -eq '1' -and (Has winget) -and (Confirm-Action 'Install LibreOffice (~700 MB, for rendering Word exports to check them)?')) {
      Invoke-Native winget install --id TheDocumentFoundation.LibreOffice -e --accept-source-agreements --accept-package-agreements
      Warn 'For page images also install poppler (pdftoppm): https://github.com/oschwartz10612/poppler-windows/releases'
    } else { Warn 'LibreOffice not installed (optional: TESTKIT_OFFICE=1). Word exports are validated but not rendered.' }

    if ($env:TESTKIT_AGENT_BROWSER -eq '1') {
      Step "Node.js >= $NodeMinMajor (for agent-browser)"
      $major = if (Has node) { [int](node -p "process.versions.node.split('.')[0]") } else { 0 }
      if ($major -ge $NodeMinMajor) { Ok "node $(node -v)" }
      else {
        if (-not (Has winget)) { Die 'winget not found. Install Node.js 22 LTS from https://nodejs.org and re-run.' }
        if (-not (Confirm-Action 'Install Node.js LTS with winget?')) { Die "Node.js >= $NodeMinMajor is required" }
        Invoke-Native winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
        Update-SessionPath
        Ok "node $(node -v)"
      }

      Step 'agent-browser + Chromium'
      if (Has agent-browser) { Ok "$(agent-browser --version)" }
      elseif (Confirm-Action 'Install agent-browser (npm -g) and its Chromium?') {
        if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { Warn 'Windows ARM64: agent-browser runs its x64 build under emulation.' }
        Invoke-Native npm install -g agent-browser
        Update-SessionPath
        Invoke-Native agent-browser install
        Ok "$(agent-browser --version)"
      } else { Warn 'skipped; testkit needs a browser tool to run tests' }
    }
  }

  # Optional tool groups (TESTKIT_WITH)
  function Install-Tool($group, $cmd, $label, $wingetId, $hint) {
    if (Has $cmd) { Ok "$label ($((Get-Command $cmd).Source))"; return }
    if (-not $wingetId) { Warn "$label not found; $hint"; return }
    if (-not (Has winget)) { Warn "winget not found; $hint"; return }
    if (-not (Confirm-Action "Install $label (TESTKIT_WITH $group)?")) { Warn "$label skipped"; return }
    try { Invoke-Native winget install --id $wingetId -e --accept-source-agreements --accept-package-agreements; Update-SessionPath; Ok "$label installed" }
    catch { Warn "$label not installed; $hint" }
  }
  if ($With -and $env:TESTKIT_SKIP_PREREQS -ne '1') {
    Step "Optional tools: $($With -join ', ')"
    if ($With -contains 'api')        { Install-Tool api hurl 'Hurl (API testing)' 'Orange-OpenSource.Hurl' 'see https://hurl.dev/docs/installation.html' }
    if ($With -contains 'mail')       { Install-Tool mail mailpit 'Mailpit (test inbox)' 'axllent.mailpit' 'see https://mailpit.axllent.org/docs/install/' }
    if ($With -contains 'db')         { Install-Tool db psql 'psql (PostgreSQL client)' '' 'install the PostgreSQL client tools (winget PostgreSQL.PostgreSQL.17 installs the full server)'
                                        Install-Tool db mysql 'mysql client' '' 'install the MySQL client (winget Oracle.MySQL)' }
    if ($With -contains 'automation') { Install-Tool automation node 'Node.js (Playwright)' 'OpenJS.NodeJS.LTS' 'install Node.js LTS'
                                        Ok 'Playwright is installed per project by the testkit-automate skill (run_suite.py --install)' }
    if ($With -contains 'video')      { Install-Tool video ffmpeg 'ffmpeg (bug and guide videos)' 'Gyan.FFmpeg' 'install ffmpeg' }
    if ($With -contains 'load')       { Install-Tool load k6 'k6 (load tests)' 'GrafanaLabs.k6' 'see https://grafana.com/docs/k6/latest/set-up/install-k6/' }
    if ($With -contains 'mobile') {
      Install-Tool mobile java 'Java (Maestro needs 17+)' 'EclipseAdoptium.Temurin.21.JDK' 'install a JDK 17+'
      if (Has maestro) { Ok 'Maestro' } else { Warn 'Maestro: download maestro.zip from the GitHub release cli-2.12.0 (github.com/mobile-dev-inc/maestro), unzip it and add its bin folder to PATH' }
      Warn 'Mobile tests also need an Android emulator or a device; testkit does not install SDKs'
    }
    if ($With -contains 'security')   { if (Has docker) { Ok 'Docker (OWASP ZAP baseline runs as a container on demand)' } else { Warn 'Docker not found: needed only for the ZAP baseline scan (winget Docker.DockerDesktop)' } }
  }

  Step 'testkit command'
  New-Item -ItemType Directory -Force -Path $TestkitHome, $BinDir | Out-Null
  @("source=$Source", "ref=$Ref") | Set-Content -Encoding ascii (Join-Path $TestkitHome 'config')

  # Download the kit to a temp folder, then swap it in.
  $kit = Join-Path $TestkitHome 'kit'
  $tmp = Join-Path $TestkitHome (".fetch." + [guid]::NewGuid().ToString('N').Substring(0, 8))
  $staged = Join-Path $tmp 'kit'
  try {
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    if (Test-Path -LiteralPath $Source -PathType Container) {
      New-Item -ItemType Directory -Force -Path $staged | Out-Null
      Get-ChildItem -LiteralPath $Source -Force | Where-Object { $_.Name -notin @('.git', 'node_modules') } |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $staged -Recurse -Force }
    } elseif ($Source -like 'git@*' -or $Source -like '*.git') {
      Invoke-Native git clone --quiet --depth 1 --branch $Ref $Source $staged
    } else {
      $zip = Join-Path $tmp 'kit.zip'
      Invoke-WebRequest -UseBasicParsing $(if ($Source -match '^https?://') { $Source.TrimEnd('/') + '/kit.zip' } else { "https://codeload.github.com/$Source/zip/$Ref" }) -OutFile $zip
      Expand-Archive $zip -DestinationPath (Join-Path $tmp 'x')
      Move-Item (Get-ChildItem (Join-Path $tmp 'x') -Directory | Select-Object -First 1).FullName $staged
    }
    if (-not (Test-Path (Join-Path $staged 'bin/testkit.ps1'))) { Die "$Source@$Ref does not look like testkit (bin/testkit.ps1 missing)" }
    foreach ($p in @("$kit.old")) { if (Test-Path $p) { Remove-Item -Recurse -Force $p } }
    if (Test-Path $kit) { Move-Item $kit "$kit.old" }
    Move-Item $staged $kit
    if (Test-Path "$kit.old") { Remove-Item -Recurse -Force "$kit.old" }
  } finally {
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
  }

  # `testkit` shim: works from cmd and PowerShell, independent of the execution policy.
  $shim = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0..\kit\bin\testkit.ps1`" %*`r`nexit /b %ERRORLEVEL%`r`n"
  [IO.File]::WriteAllText((Join-Path $BinDir 'testkit.cmd'), $shim)

  $userPath = [string][Environment]::GetEnvironmentVariable('Path', 'User')
  if (-not (($userPath -split ';') -contains $BinDir)) {
    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ";$BinDir").TrimStart(';'), 'User')
    Ok "added $BinDir to your user PATH"
  }
  $env:Path = "$env:Path;$BinDir"
  $version = (Get-Content (Join-Path $kit '.claude-plugin/plugin.json') -Raw | ConvertFrom-Json).version
  Ok "testkit $version -> $BinDir\testkit.cmd"

  if ($With -contains 'knowledge') {
    Step 'Knowledge graph (Graphiti)'
    if (-not (Has docker)) { Warn 'Docker not found: install Docker Desktop, then run: testkit graph up' }
    elseif (Confirm-Action 'Start Graphiti now, or reuse one already running? (first start downloads a ~3.7 GB image, about 11 GB on disk; needs an LLM key such as OPENAI_API_KEY in your environment, or Ollama)') {
      & (Join-Path $BinDir 'testkit.cmd') graph up
      if ($LASTEXITCODE -ne 0) { Warn "Graphiti not started; fix the message above, then run: testkit graph up" }
    } else { Warn "skipped; run 'testkit graph up' later. testkit keeps knowledge in files until a graph is available" }
  }

  Step 'Done'
  Write-Host '  Open a NEW terminal, go to a project folder and run:'
  Write-Host '    testkit init'
  Write-Host '  Then start Claude Code there and run /testkit-config.'
  Write-Host '  Check your setup any time with: testkit doctor'
}
