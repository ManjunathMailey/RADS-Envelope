# Reproduce the results:  powershell -ExecutionPolicy Bypass -File .\reproduce.ps1
# Runs the test suite, the robustness test (rule-generated gold) and the DEVELOPMENT real-case comparison.
# It never scores the held-out test split. Results are copied to results\<timestamp>\.
Set-Location $PSScriptRoot
$ErrorActionPreference = "Stop"
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run setup.ps1 first (.venv not found)." }
Remove-Item Env:\RADS_RUN_TEST -ErrorAction SilentlyContinue        # make sure the test guard stays closed
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$out = Join-Path "results" $stamp
New-Item -ItemType Directory -Force $out | Out-Null

Write-Host "1/3 Test suite" -ForegroundColor Green
& $py -m pytest -q 2>&1 | Tee-Object -FilePath (Join-Path $out "pytest.txt")
if ($LASTEXITCODE -ne 0) { throw "Tests failed; see $out\pytest.txt" }

Write-Host "2/3 Robustness test (rule-generated gold), 200 reports" -ForegroundColor Green
& $py -m radsenvelope.evaluation.benchmark --n 200 --seed 7 --compare 2>&1 | Tee-Object -FilePath (Join-Path $out "robustness.txt")
Copy-Item data\benchmark\results_comparison.json $out

Write-Host "3/3 Real cases, development split" -ForegroundColor Green
& $py -m radsenvelope.evaluation.real_cases --compare --split dev 2>&1 | Tee-Object -FilePath (Join-Path $out "real_dev.txt")
Copy-Item data\real\results.comparison.dev.json $out

Write-Host "Done. Results in $out" -ForegroundColor Green
