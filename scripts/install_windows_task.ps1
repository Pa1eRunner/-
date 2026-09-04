$ErrorActionPreference = "Stop"

$taskName = "QipaiNewsBot"
$projectRoot = Split-Path -Parent $PSScriptRoot
$executable = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$configPath = Join-Path $projectRoot "config\config.yaml"

if (-not (Test-Path -LiteralPath $executable)) {
    throw "Bot executable not found: $executable"
}

$action = New-ScheduledTaskAction `
    -Execute $executable `
    -Argument "-m newsbot.app --config `"$configPath`"" `
    -WorkingDirectory $projectRoot
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$watchdogTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$task = New-ScheduledTask `
    -Action $action `
    -Trigger @($logonTrigger, $watchdogTrigger) `
    -Principal $principal `
    -Settings $settings `
    -Description "棋牌游戏行业舆情钉钉推送机器人"

Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Output "Scheduled task installed and started: $taskName"
