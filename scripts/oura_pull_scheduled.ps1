# Run by the "TinyML Oura pull" scheduled task (REQ-OURA-04): pull the last days of Oura data
# (always at least 3, to catch late ring syncs) and append the result to data\oura\pull.log.
# No sign-in needed: the app renews its token from Windows Credential Manager.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$log = Join-Path $repo "data\oura\pull.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
$env:PYTHONIOENCODING = "utf-8"
"==== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')" | Out-File $log -Append -Encoding utf8
& "$repo\venv\Scripts\python.exe" -m hub.oura_app pull --days 3 *>&1 | Out-File $log -Append -Encoding utf8
"exit $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
# Keep the log short: last 2000 lines.
$lines = Get-Content $log -Encoding utf8
if ($lines.Count -gt 2000) { $lines[-2000..-1] | Set-Content $log -Encoding utf8 }
exit $LASTEXITCODE
