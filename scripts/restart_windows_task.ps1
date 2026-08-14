$ErrorActionPreference = "Stop"

$taskName = "QipaiNewsBot"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
if ($task.State -eq "Running") {
    Stop-ScheduledTask -TaskName $taskName
    do {
        Start-Sleep -Milliseconds 500
        $task = Get-ScheduledTask -TaskName $taskName
    } while ($task.State -eq "Running")
}
Start-ScheduledTask -TaskName $taskName
Write-Output "Scheduled task restarted: $taskName"

