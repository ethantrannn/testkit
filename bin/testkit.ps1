<#
  testkit CLI (Windows). Installed by install.ps1; run as `testkit` through %USERPROFILE%\.testkit\bin\testkit.cmd.

    testkit init [dir] [--agents LIST] [--force] [--offline]
                                               install/refresh testkit in a project (default: current dir)
                                               LIST: auto (default), all, or claude,codex,cursor,gemini,copilot
    testkit update [dir]                       same as init, for a project that already has testkit
    testkit doctor                             check coding agents, browser-use, Chrome and the kit
    testkit graph up|status|down|connect|...   Graphiti knowledge graph: reuse an existing one or start one (Docker)
    testkit version                            print kit version
    testkit help

  Env: TESTKIT_HOME (default ~\.testkit), TESTKIT_SOURCE / TESTKIT_REF override ~\.testkit\config.
#>
$ErrorActionPreference = 'Stop'

$TestkitHome = if ($env:TESTKIT_HOME) { $env:TESTKIT_HOME } else { Join-Path $HOME '.testkit' }
$Kit = Join-Path $TestkitHome 'kit'
$Conf = Join-Path $TestkitHome 'config'

function Step($m) { Write-Host "`n==> $m" }
function Ok($m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [x]  $m" -ForegroundColor Red }
function Die($m)  { Fail $m; exit 1 }
function Has($c)  { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

function Get-Conf($key) {
  if (-not (Test-Path $Conf)) { return '' }
  $line = Get-Content $Conf | Where-Object { $_ -like "$key=*" } | Select-Object -Last 1
  if ($line) { return $line.Substring($key.Length + 1) } else { return '' }
}
$Source = if ($env:TESTKIT_SOURCE) { $env:TESTKIT_SOURCE } else { Get-Conf 'source' }
$Ref = if ($env:TESTKIT_REF) { $env:TESTKIT_REF } else { Get-Conf 'ref' }
if (-not $Ref) { $Ref = 'main' }

function Get-KitVersion($dir) {
  $p = Join-Path $dir '.claude-plugin/plugin.json'
  if (Test-Path $p) { (Get-Content $p -Raw | ConvertFrom-Json).version } else { '' }
}

# Copy a kit folder, skipping VCS and generated files.
function Copy-KitTree($from, $to) {
  New-Item -ItemType Directory -Force -Path $to | Out-Null
  Get-ChildItem -LiteralPath $from -Force | Where-Object { $_.Name -notin @('.git', 'node_modules') } |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $to -Recurse -Force }
  $refs = Join-Path $to 'skills/browser-testing/references'
  if (Test-Path $refs) { Remove-Item -Recurse -Force $refs }
}

# Download the latest kit from $Source into $Kit, swapping directories.
# $Source is a GitHub "owner/repo", a git URL, or a local folder.
function Update-KitCache {
  if (-not $Source) { Die 'No kit source configured. Re-run the installer or set TESTKIT_SOURCE.' }
  New-Item -ItemType Directory -Force -Path $TestkitHome | Out-Null
  $tmp = Join-Path $TestkitHome (".fetch." + [guid]::NewGuid().ToString('N').Substring(0, 8))
  $staged = Join-Path $tmp 'kit'
  try {
    if (Test-Path -LiteralPath $Source -PathType Container) {
      Copy-KitTree $Source $staged
    } elseif ($Source -like 'git@*' -or $Source -like '*.git') {
      git clone --quiet --depth 1 --branch $Ref $Source $staged
      if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
      Remove-Item -Recurse -Force (Join-Path $staged '.git')
    } else {
      New-Item -ItemType Directory -Force -Path $tmp | Out-Null
      $zip = Join-Path $tmp 'kit.zip'
      Invoke-WebRequest -UseBasicParsing $(if ($Source -match '^https?://') { $Source.TrimEnd('/') + '/kit.zip' } else { "https://codeload.github.com/$Source/zip/$Ref" }) -OutFile $zip
      Expand-Archive $zip -DestinationPath (Join-Path $tmp 'x')
      $top = Get-ChildItem (Join-Path $tmp 'x') -Directory | Select-Object -First 1
      Move-Item $top.FullName $staged
    }
    if (-not (Test-Path (Join-Path $staged '.claude-plugin/plugin.json'))) { throw "$Source@$Ref is not a testkit kit" }
    $old = "$Kit.old"
    if (Test-Path $old) { Remove-Item -Recurse -Force $old }
    if (Test-Path $Kit) { Move-Item $Kit $old }
    Move-Item $staged $Kit
    if (Test-Path $old) { Remove-Item -Recurse -Force $old }
    return $true
  } catch {
    Fail $_.Exception.Message
    return $false
  } finally {
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
  }
}

# browser-use 1.x (the heredoc CLI); 0.x is a different tool.
function Test-BrowserUse { (Has browser-use) -and ((browser-use --version 2>$null | Select-Object -First 1) -match '^browser-use [1-9]') }

function Get-Manifest($dir) {
  foreach ($rel in @('qa/.testkit-manifest', '.claude/.testkit-manifest')) {
    $p = Join-Path $dir $rel
    if (Test-Path $p) { return $p }
  }
  return $null
}

function Invoke-Py {
  if (Has uv) { & uv run --no-project --quiet python @args }
  elseif (Has python) { & python @args }
  else { Die 'Neither uv nor python found. Install uv: irm https://astral.sh/uv/install.ps1 | iex' }
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Invoke-Init([string[]]$argv, [bool]$requireManifest) {
  $dir = '.'; $force = $false; $offline = $false; $agents = ''
  for ($i = 0; $i -lt $argv.Count; $i++) {
    $a = $argv[$i]
    switch -Regex ($a) {
      '^--force$'    { $force = $true; break }
      '^--offline$'  { $offline = $true; break }
      '^--agents=.+' { $agents = $a.Substring(9); break }
      '^--agents$'   { $i++; if ($i -ge $argv.Count) { Die '--agents needs a value (auto, all, or claude,codex,cursor,gemini,copilot)' }; $agents = $argv[$i]; break }
      '^-'           { Die "Unknown option: $a" }
      default        { $dir = $a }
    }
  }
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $dir = (Resolve-Path $dir).Path
  if ($dir.TrimEnd('\', '/') -eq $HOME.TrimEnd('\', '/')) { Die 'Refusing to install into your home folder. cd into a project first.' }
  if ($requireManifest -and -not (Get-Manifest $dir)) { Die "testkit is not installed in $dir. Run: testkit init" }

  Write-Host "testkit init -> $dir"

  Step 'Fetching the latest kit'
  if ($offline) { Warn 'offline: using cached kit' }
  elseif (Update-KitCache) { Ok "kit $(Get-KitVersion $Kit) from $Source@$Ref" }
  elseif (Test-Path $Kit) { Warn "download failed; using cached kit $(Get-KitVersion $Kit)" }
  else { Die 'Could not download the kit and no cached copy exists.' }

  $pyArgs = @((Join-Path $Kit 'bin/testkit_sync.py'), '--kit', $Kit, '--project', $dir, '--source', "$Source@$Ref")
  if ($agents) { $pyArgs += @('--agents', $agents) }
  if ($force) { $pyArgs += '--force' }
  Invoke-Py @pyArgs
}

function Invoke-Doctor {
  $status = 0
  Step 'Tools'
  if (Has node) { Ok "node $(node -v) (optional, for agent-browser)" }
  $found = $false
  foreach ($a in @('claude', 'codex', 'cursor-agent', 'gemini', 'copilot')) {
    if (Has $a) { Ok "$a $(& $a --version 2>$null | Select-Object -First 1)"; $found = $true }
  }
  if (-not $found) { Fail 'no coding agent CLI found (Claude Code, Codex, Cursor, Gemini CLI or Copilot)'; $status = 1 }
  if (Has uv) { Ok "$(uv --version)" } else { Warn 'uv not found (needed to install/update browser-use)' }
  if (Test-BrowserUse) {
    Ok "$(browser-use --version | Select-Object -First 1)"
    $bash = Get-Command bash -ErrorAction SilentlyContinue
    if ($bash) {
      $tmpd = Join-Path ([IO.Path]::GetTempPath()) ("testkit-doctor-" + [guid]::NewGuid().ToString('N').Substring(0, 6))
      New-Item -ItemType Directory -Force -Path $tmpd | Out-Null
      $script = (Join-Path $Kit 'skills/browser-testing/scripts/bu-session.sh').Replace('\', '/')
      Push-Location $tmpd
      try {
        $out = "new_tab(`"data:text/html,<h1>testkit ok</h1>`")`nwait_for_load()`nprint(js(`"document.querySelector('h1').textContent`"))`n" | & $bash.Source $script run testkit-doctor 2>&1
        if (($out -join "`n") -match 'testkit ok') { Ok 'isolated browser session works' } else { Fail 'isolated browser session failed (Chrome installed? try: browser-use --doctor)'; $status = 1 }
        & $bash.Source $script stop testkit-doctor *> $null
      } finally { Pop-Location; Remove-Item -Recurse -Force $tmpd -ErrorAction SilentlyContinue }
    } else { Warn 'bash (Git Bash) not found; Claude Code on Windows needs Git for Windows' }
  } else { Fail 'browser-use 1.x not found (uv tool install browser-use)'; $status = 1 }
  if (Has agent-browser) { Ok "$(agent-browser --version) (optional)" }
  Step 'Word documents'
  if (Has pandoc) { Ok "$(pandoc --version | Select-Object -First 1)" } else { Warn 'pandoc not found: agents cannot read .docx specs' }
  if ((Has soffice) -or (Test-Path "$env:ProgramFiles\LibreOffice\program\soffice.exe")) { Ok 'LibreOffice' } else { Warn 'LibreOffice not found (optional: renders Word exports for a visual check)' }
  if (Has pdftoppm) { Ok 'pdftoppm' } else { Warn 'pdftoppm not found (optional, poppler)' }
  Step 'Optional tools (install with TESTKIT_WITH=<group>)'
  $missing = @()
  foreach ($pair in @('hurl:api', 'mailpit:mail', 'psql:db', 'mysql:db', 'node:automation', 'ffmpeg:video', 'k6:load', 'maestro:mobile', 'docker:security')) {
    $t, $g = $pair -split ':'
    if (Has $t) { Ok "$t ($g)" } else { $missing += "$t($g)" }
  }
  if ($missing) { Write-Host "  - not installed: $($missing -join ' ')" }
  Step 'Knowledge graph'
  if (Test-Path $Kit) {
    $script = Join-Path $Kit 'bin/testkit_graph.py'
    $g = if (Has uv) { uv run --no-project --quiet python $script detect 2>$null | Select-Object -Last 1 }
         elseif (Has python) { python $script detect 2>$null | Select-Object -Last 1 } else { '' }
    if ($g -like 'http*') { Ok "Graphiti: $g" } else { Warn 'no Graphiti found: project knowledge stays in qa/knowledge/ files (start one with: testkit graph up)' }
  }
  Step 'Kit'
  if (Test-Path $Kit) { Ok "cached kit $(Get-KitVersion $Kit) at $Kit (source: $Source@$Ref)" } else { Fail 'no cached kit; run testkit init'; $status = 1 }
  $m = Get-Manifest (Get-Location).Path
  if ($m) {
    $c = Get-Content $m
    $v = ($c | Where-Object { $_ -like '# version: *' }) -replace '^# version: ', ''
    $ag = ($c | Where-Object { $_ -like '# agents: *' }) -replace '^# agents: ', ''
    Ok "this project: $v for $ag"
  } else { Warn "testkit not installed in $((Get-Location).Path)" }
  exit $status
}

$cmd = if ($args.Count -gt 0) { $args[0] } else { 'help' }
$rest = if ($args.Count -gt 1) { [string[]]$args[1..($args.Count - 1)] } else { [string[]]@() }
switch ($cmd) {
  'init'    { Invoke-Init $rest $false }
  'update'  { Invoke-Init $rest $true }
  'doctor'  { Invoke-Doctor }
  'graph'   { if (-not (Test-Path $Kit)) { Die "No kit at $Kit. Re-run the installer." }; Invoke-Py (Join-Path $Kit 'bin/testkit_graph.py') @rest }
  { $_ -in 'version', '-v', '--version' } { Write-Host "testkit $(Get-KitVersion $Kit)" }
  { $_ -in 'help', '-h', '--help' } { (Get-Content $PSCommandPath -TotalCount 13 | Select-Object -Skip 1) -replace '^  ', '' | Write-Host }
  default   { Die "Unknown command: $cmd (try: testkit help)" }
}
