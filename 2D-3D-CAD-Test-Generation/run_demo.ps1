# Starts the MTI demo (docs/guides/demo/2026-11-02-mti-demo-runbook.md) in this window.
# Usage: .\run_demo.ps1 [hero|fallback|backup]   (default hero; replay mode, $0)
param([string]$Which = "hero")
$env:PYTHONUTF8 = "1"
$env:API_BUDGET_USD = "50"
$py = "C:\Users\gingw\Desktop\AILOTFALL\mti-2d-3d\.venv\Scripts\python.exe"
$out = "C:\Users\gingw\Desktop\AILOTFALL\mti-2d-3d\2D-3D-CAD-Test-Generation\output"
$demo = Join-Path $PSScriptRoot "demo.py"
switch ($Which) {
    "fallback" { & $py $demo --part 2N2664 --from $out }
    "backup"   { & $py $demo --part A00122E --from $out }
    default    { & $py $demo --part 2N2664 --from (Join-Path $out "2n2664_replan") }
}
