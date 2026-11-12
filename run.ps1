# Start the app:  powershell -ExecutionPolicy Bypass -File .\run.ps1
Set-Location $PSScriptRoot
if (-not $env:RADS_MODEL) { $env:RADS_MODEL = "qwen2.5:7b-instruct" }
$port = 8000
Write-Host "RADS-Envelope  http://localhost:$port   model: $env:RADS_MODEL   (Ctrl+C to stop)" -ForegroundColor Green
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile -Command Start-Sleep 4; Start-Process http://localhost:$port"
& ".\.venv\Scripts\python.exe" -m uvicorn radsenvelope.api.app:app --port $port
