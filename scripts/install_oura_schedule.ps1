# Registers (or replaces) the "TinyML Oura pull" scheduled task: runs scripts\oura_pull_scheduled.ps1
# daily at 09:30 and 21:30 as the current user, only while that user is logged on (the Oura tokens are
# in this user's Credential Manager), and catches up after the laptop was off or asleep.
#   .\scripts\install_oura_schedule.ps1            # install / update
#   .\scripts\install_oura_schedule.ps1 -Remove    # uninstall
param([switch]$Remove, [string[]]$Times = @("09:30", "21:30"))
$name = "TinyML Oura pull"
if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    "Removed '$name'."; exit 0
}
$script = Join-Path $PSScriptRoot "oura_pull_scheduled.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$triggers = $Times | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Settings $settings -Principal $principal `
    -Description "Pulls Oura ring data for the TinyML EEG project (hub/oura_app). Log: data\oura\pull.log" -Force | Out-Null
"Registered '$name' at $($Times -join ', ') daily."
