# McAgent UI launcher (Windows PowerShell). ASCII only (PowerShell 5.1 reads BOM-less files as ANSI).
#   .\run.ps1                       auto-detect the pipeline repo
#   .\run.ps1 -Repo C:\path\repo    explicit repo (or env MCAGENT_REPO)
#   $env:PORT=8210; .\run.ps1 ...   port (default 8200)
# Env: MCAGENT_REPO, MCAGENT_DATA (default FINAL_UI\data), MCAGENT_PYTHON (reuse interpreter, skip venv/installs).
param([string]$Repo = $env:MCAGENT_REPO, [string]$Port = $(if ($env:PORT) { $env:PORT } else { "8200" }))
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Repo($d) { return ((Test-Path (Join-Path $d "main.py")) -and (Test-Path (Join-Path $d "pipeline") -PathType Container)) }

if (-not $Repo) {
    $dir = Split-Path -Parent $Here
    while ($dir) {
        $found = @()
        if (Test-Repo $dir) { $found += $dir }
        Get-ChildItem -Path $dir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.FullName -ne $Here -and (Test-Repo $_.FullName)) { $found += $_.FullName }
        }
        if ($found.Count -eq 1) { $Repo = $found[0]; Write-Host "Auto-detected pipeline repo: $Repo"; break }
        if ($found.Count -gt 1) { throw ("Several pipeline repos found; choose one with -Repo <path>:`n  " + ($found -join "`n  ")) }
        $parent = Split-Path -Parent $dir
        if (-not $parent -or $parent -eq $dir) { break }
        $dir = $parent
    }
    if (-not $Repo) {
        throw "No pipeline repo found above $Here. A repo is a folder with main.py and a pipeline\ package. Use: .\run.ps1 -Repo C:\path\to\repo  (or set MCAGENT_REPO)."
    }
}
if (-not (Test-Path $Repo)) { throw "Repo path does not exist: $Repo" }
$Repo = (Resolve-Path $Repo).Path
if (-not (Test-Repo $Repo)) { throw "$Repo is not a pipeline repo: it needs main.py and a pipeline\ package." }
if (-not (Select-String -Path (Join-Path $Repo "main.py") -Pattern "--no-export" -SimpleMatch -Quiet)) { Write-Warning "$Repo\main.py has no --no-export flag. Runs and demos will fail on a repo whose CLI differs from what the UI drives." }
$env:MCAGENT_REPO = $Repo
if (-not $env:MCAGENT_DATA) { $env:MCAGENT_DATA = Join-Path $Here "data" }

$PyMin = [Version]"3.10"; $PyMaxExcl = [Version]"3.13"
function Test-PyCompatible($exe) {
    if (-not $exe) { return $false }
    try { $v = & $exe -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null } catch { return $false }
    if (-not $v) { return $false }
    try { $ver = [Version]$v } catch { return $false }
    return ($ver -ge $PyMin -and $ver -lt $PyMaxExcl)
}
function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($tag in @("3.12", "3.11", "3.10")) {
            $p = (& py "-$tag" -c "import sys;print(sys.executable)" 2>$null)
            if ($LASTEXITCODE -eq 0 -and (Test-PyCompatible $p)) { return $p }
        }
    }
    foreach ($name in @("python", "python3")) {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if ($c -and (Test-PyCompatible $c.Source)) { return $c.Source }
    }
    return $null
}

if ($env:MCAGENT_PYTHON) {
    $Py = $env:MCAGENT_PYTHON
} else {
    $Venv = Join-Path $Here ".venv"
    $Py = Join-Path $Venv "Scripts\python.exe"
    if (-not (Test-Path $Py)) {
        $BasePy = Find-Python
        if (-not $BasePy -and (Get-Command winget -ErrorAction SilentlyContinue)) {
            Write-Host "Installing Python 3.12 via winget (one-time) ..."
            winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
            $BasePy = Find-Python
        }
        if (-not $BasePy) { throw "No compatible Python (>=3.10,<3.13). Install Python 3.12 or set MCAGENT_PYTHON." }
        Write-Host "Creating venv $Venv with $BasePy ..."
        & $BasePy -m venv $Venv
        if (-not (Test-Path $Py)) { throw "Could not create the venv with $BasePy" }
    }
    $ReqRepo = Join-Path $Repo "requirements.txt"
    $ReqUi = Join-Path $Here "server\requirements-ui.txt"
    $files = @($ReqUi); if (Test-Path $ReqRepo) { $files = @($ReqRepo) + $files }
    $hash = (($files | ForEach-Object { (Get-FileHash $_ -Algorithm MD5).Hash }) -join "").Substring(0, 16)
    $Stamp = Join-Path $Venv (".installed-" + $hash)
    if (-not (Test-Path $Stamp)) {
        Write-Host "Installing dependencies (repo + UI) ..."
        & $Py -m pip install -q --upgrade pip
        if (Test-Path $ReqRepo) { & $Py -m pip install -q -r $ReqRepo; if ($LASTEXITCODE -ne 0) { throw "pip install (repo deps) failed." } }
        & $Py -m pip install -q -r $ReqUi
        if ($LASTEXITCODE -ne 0) { throw "pip install (UI deps) failed." }
        New-Item -ItemType File -Path $Stamp | Out-Null
    }
}

Write-Host ""
Write-Host "  McAgent UI  ->  http://127.0.0.1:$Port"
Write-Host "  repo: $Repo"
Write-Host "  data: $env:MCAGENT_DATA"
Write-Host ""
Start-Process "http://127.0.0.1:$Port/"
& $Py -m uvicorn app:app --app-dir (Join-Path $Here "server") --host 127.0.0.1 --port $Port
