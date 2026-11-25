# Starts the latest Solid Flow UI on http://127.0.0.1:8200 and opens it. Safe to run again: it stops an older copy first.
# Usage:  powershell -ExecutionPolicy Bypass -File C:\Users\joeka\OneDrive\Desktop\UI_Astra\FINAL_UI\start-ui.ps1 [#/page]
param([string]$Page = "#/scoring")

$ui   = $PSScriptRoot
$repo = Join-Path (Split-Path $ui -Parent) "2D-3D-CAD-Test-Generation"
$py   = Join-Path $ui ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Get-NetTCPConnection -LocalPort 8200 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep 1

$env:MCAGENT_REPO = $repo
$env:PYTHONUTF8 = "1"
Start-Process -FilePath $py -ArgumentList "-m", "uvicorn", "app:app", "--app-dir", "server", "--host", "127.0.0.1", "--port", "8200" -WorkingDirectory $ui -WindowStyle Hidden

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep 1
    try { if ((Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8200/api/status" -TimeoutSec 2).StatusCode -eq 200) { break } } catch { }
}
Start-Process "http://127.0.0.1:8200/$Page"
Write-Host "Solid Flow is running at http://127.0.0.1:8200/$Page"
