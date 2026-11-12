# One-time setup:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$model = if ($env:RADS_MODEL) { $env:RADS_MODEL } else { "qwen2.5:7b-instruct" }

Write-Host "[1/4] Virtual environment" -ForegroundColor Cyan
if (-not (Test-Path .venv)) { python -m venv .venv }
$py = ".\.venv\Scripts\python.exe"

Write-Host "[2/4] Python packages" -ForegroundColor Cyan
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r requirements.txt --quiet

Write-Host "[3/4] Local model ($model)" -ForegroundColor Cyan
if (Get-Command ollama -ErrorAction SilentlyContinue) { ollama pull $model }
else { Write-Host "Ollama not found: the app will use the lexicon extractor." -ForegroundColor Yellow }

Write-Host "[4/4] Tests" -ForegroundColor Cyan
& $py -m pytest

Write-Host "Done. Start with: powershell -ExecutionPolicy Bypass -File .\run.ps1" -ForegroundColor Green
