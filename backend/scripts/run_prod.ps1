# Runs uvicorn in the foreground with log files; used by install_windows_task.ps1 (and fine to run by hand).
param([string]$Args = "-m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*")
$backend = Split-Path -Parent $PSScriptRoot
Set-Location $backend
New-Item -ItemType Directory -Force "$backend\logs" | Out-Null
$python = "$backend\.venv\Scripts\python.exe"
$argList = $Args -split " "
& $python @argList 1>> "$backend\logs\bot.out.log" 2>> "$backend\logs\bot.err.log"
